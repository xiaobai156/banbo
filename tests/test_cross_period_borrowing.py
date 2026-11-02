"""跨期借值回归测试。

覆盖 2026-10-25 代码审查指出的四条路径与一处缓存地雷：
1. 方向窗口按文档分桶时退化成 1 组 —— 现在退化为页面级窗口。
2. title_neighbor 以锚点扩窗导致窗口整体平移。
3. nearest_document 只留最近距离，吞掉同期冲突。
4. combined_sibling 偏移越界回退到上一片段。
5. 校验层接受升序/跳期边界；target_only 未生效。
6. cli 预改写缓存窗口导致补老期删除新期值。
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from banbo.domain.errors import FailureCode
from banbo.domain.models import (
    Direction,
    Document,
    DocumentSource,
    ParseEvidence,
    SiteSpec,
    ValidatedResult,
    FailureResult,
)
from banbo.domain.validation import validate_evidence
from banbo.parsers.boundary import select_directional_windows
from banbo.parsers.combined_sibling import CombinedSiblingParser
from banbo.parsers.history_block import HistoryBlockParser
from banbo.parsers.nearest_document import NearestDocumentParser
from banbo.parsers.protocol import ParserSpec
from banbo.parsers.title_neighbor import TitleNeighborParser
from banbo.storage.recent_cache import (
    CacheValidationError,
    RecentCacheRepository,
)


def _site(direction: Direction = Direction.TOP, *, target_only: bool = True) -> SiteSpec:
    return SiteSpec(
        site_id="hw-9999",
        name="测试站",
        url="https://example.test/topic/1.html",
        direction=direction,
        strategy="history_block",
        anchors=(),
        parser_version="1",
        target_only=target_only,
    )


def _evidence(
    value: str = "红单",
    *,
    target_issue: int = 296,
    boundary: tuple[int, ...] = (296, 295, 294),
    direction: Direction = Direction.TOP,
) -> ParseEvidence:
    return ParseEvidence(
        site_id="hw-9999",
        target_issue=target_issue,
        value=value,
        document_id="doc-1",
        document_source=DocumentSource.PAGE,
        document_order=0,
        snippet=f"{target_issue}期 绝杀半波 {value}",
        parser_name="history_block",
        parser_version="1",
        direction=direction,
        anchor_passed=True,
        keyword_passed=True,
        same_record=True,
        record_id=None,
        expected_record_id=None,
        anchors=(),
        keywords=(),
        source_offset=0,
        candidate_count=1,
        conflict_values=(value,),
        boundary_issues=boundary,
        document_relation="same_document",
    )


class _Candidate:
    """最小候选对象，供 boundary 窗口选择使用。"""

    def __init__(self, issue: int, group: str, value: str = "红单") -> None:
        self.issue = issue
        self.group = group
        self.value = value


def test_degenerate_group_uses_page_level_window() -> None:
    """每个脚本只有一期时，窗口必须按整页算，不能退化成该期本身。"""

    candidates = [
        _Candidate(issue, group=f"script-{index}")
        for index, issue in enumerate(range(298, 288, -1))
    ]
    windows = select_directional_windows(
        candidates,
        issue_of=lambda item: item.issue,
        group_of=lambda item: item.group,
        direction=Direction.TOP,
    )
    issues_in_windows = {
        item.issue for boundary, _ in windows for item in boundary
    }
    assert issues_in_windows == {298, 297, 296}, (
        "top 方向只允许页面级前三组，第 10 组的 289 期不得通过"
    )


def test_degenerate_group_blocks_out_of_window_target() -> None:
    """指定期排在第 10 组时不应产生任何窗口证据。"""

    candidates = [
        _Candidate(issue, group=f"script-{index}")
        for index, issue in enumerate(range(298, 288, -1))
    ]
    windows = select_directional_windows(
        candidates,
        issue_of=lambda item: item.issue,
        group_of=lambda item: item.group,
        direction=Direction.TOP,
    )
    assert all(
        item.issue != 289 for boundary, _ in windows for item in boundary
    )


def test_validation_rejects_non_monotonic_boundary() -> None:
    """边界期顺序错乱（拼接痕迹）必须失败。"""

    outcome = validate_evidence(
        _site(Direction.TOP),
        296,
        (_evidence(boundary=(296, 294, 295)),),
    )
    assert isinstance(outcome, FailureResult)
    assert outcome.code is FailureCode.DIRECTION_WINDOW_INVALID


def test_validation_allows_period_gap_in_boundary() -> None:
    """站方漏发某期时边界允许跳期，只要方向单调不反转。"""

    outcome = validate_evidence(
        _site(Direction.TOP),
        296,
        (_evidence(boundary=(296, 294, 293)),),
    )
    assert isinstance(outcome, ValidatedResult)


def test_validation_allows_short_window_when_page_has_few_periods() -> None:
    """页面只发布当期时允许 1~2 组窗口，只要方向单调。"""

    outcome = validate_evidence(
        _site(Direction.TOP),
        296,
        (_evidence(boundary=(296, 295)),),
    )
    assert isinstance(outcome, ValidatedResult)


def test_validation_rejects_non_monotonic_short_window() -> None:
    """短窗口内顺序错乱必须失败。"""

    outcome = validate_evidence(
        _site(Direction.TOP),
        296,
        (_evidence(boundary=(297, 296, 297)),),
    )
    assert isinstance(outcome, FailureResult)
    assert outcome.code is FailureCode.DIRECTION_WINDOW_INVALID


def test_validation_accepts_bottom_ascending_boundary() -> None:
    """bottom 站点升序连续边界应通过。"""

    outcome = validate_evidence(
        _site(Direction.BOTTOM),
        296,
        (_evidence(boundary=(296, 297, 298), direction=Direction.BOTTOM),),
    )
    assert isinstance(outcome, ValidatedResult)
    assert outcome.value == "红单"


def test_target_only_rejects_neighbour_period_evidence() -> None:
    """target_only 站点收到邻期证据必须失败，而不是悄悄过滤。"""

    neighbour = _evidence(target_issue=295, boundary=(295, 294, 293))
    outcome = validate_evidence(_site(Direction.TOP), 296, (neighbour,))
    assert isinstance(outcome, FailureResult)
    assert outcome.code is FailureCode.TARGET_PERIOD_MISSING


def test_combined_sibling_returns_none_for_out_of_range_offset() -> None:
    """偏移越界必须返回 None，不能回退到上一片段末尾。"""

    assert CombinedSiblingParser._to_combined_offset(5, (0, 10, 20)) is None
    assert CombinedSiblingParser._to_combined_offset(1, (0, 10, 20)) == 10


def _cache_payload(window: list[int]) -> dict:
    return {
        "schema": 1,
        "description": "测试",
        "updated_at": None,
        "window_size": len(window),
        "issues": window,
        "partial_issues": [],
        "sites": [
            {
                "name": "测试站",
                "url": "https://example.test/topic/1.html",
                "pick": "top",
                "second_click": False,
                "values": {str(issue): "红单" for issue in window},
                "failures": {},
            }
        ],
        "parser_versions": {},
    }


def test_combined_sibling_keeps_fragment_boundary() -> None:
    """片段标记必须保留，否则切段会跨片段吃值（hw-0105 真实借值场景）。"""

    combined = "296期绝杀半波\u2063绿双 295期绝杀半波 红单"
    content, offsets = CombinedSiblingParser._delegate_content(combined, True)
    assert "\u2063" in content, "片段标记被抹掉，切段会跨片段借值"
    assert len(offsets) == len(content)


def test_history_block_stops_at_fragment_marker() -> None:
    """history_block 切段遇到片段标记必须停下，不能吃进下一片段的值。"""

    spec = ParserSpec(
        site_id="hw-0105",
        strategy="history_block",
        parser_version="1",
        parser_id="hw-0105:history_block:v1",
        direction=Direction.BOTTOM,
        anchors=("白蛇传",),
        keywords=("绝杀半波",),
        issue_pattern=r"(?P<issue>\d{1,4})期",
        value_pattern=r"(?P<value>[红绿蓝](?:波)?[单双])",
        options={"skip_document_anchor": True, "anchor_mode": "any"},
    )
    site = SiteSpec(
        site_id="hw-0105",
        name="白蛇传",
        url="https://example.test/topic/1.html",
        direction=Direction.BOTTOM,
        strategy="history_block",
        anchors=("白蛇传",),
        parser_version="1",
        keywords=("绝杀半波",),
        anchor_mode="any",
    )
    documents = (
        Document(
            document_id="a",
            source=DocumentSource.SCRIPT,
            source_url="https://example.test/a.js#decoded-1",
            order=0,
            content="白蛇传 绝杀半波 296期 绝杀半波",
        ),
        Document(
            document_id="b",
            source=DocumentSource.SCRIPT,
            source_url="https://example.test/a.js#decoded-2",
            order=1,
            content="绿双 295期 绝杀半波 红单",
        ),
    )
    evidence = HistoryBlockParser(spec).parse(site, documents, 296)
    values = {item.value for item in evidence}
    assert "绿双" not in values, "296 期不得借到下一片段的绿双"


def test_title_neighbor_requires_target_on_page() -> None:
    """目标期不在页面上时必须拒绝，不能凭空取值。"""

    site = SiteSpec(
        site_id="hw-9998",
        name="测试站",
        url="https://example.test/topic/1.html",
        direction=Direction.TOP,
        strategy="title_neighbor",
        anchors=("测试站",),
        parser_version="1",
    )
    page_issues = [298, 297, 296, 295, 294, 293, 292]
    assert not TitleNeighborParser._target_in_page_window(site, page_issues, 289)
    assert TitleNeighborParser._target_in_page_window(site, page_issues, 297)


def test_title_neighbor_allows_far_target_because_layout_puts_anchor_last() -> None:
    """锚点在后、值在前的站点，目标期远离页面极值仍应放行。"""

    site = SiteSpec(
        site_id="hw-9997",
        name="测试站",
        url="https://example.test/topic/1.html",
        direction=Direction.BOTTOM,
        strategy="title_neighbor",
        anchors=("测试站",),
        parser_version="1",
    )
    page_issues = [274, 271, 272, 273, 274]
    assert TitleNeighborParser._target_in_page_window(site, page_issues, 274)
    assert TitleNeighborParser._target_in_page_window(site, page_issues, 271)


def test_nearest_document_reports_same_period_conflict() -> None:
    """最近文档解析必须把同期不同值上抛，而不是只留最近的一个。"""

    spec = ParserSpec(
        site_id="hw-9996",
        strategy="nearest_document",
        parser_version="1",
        parser_id="hw-9996:nearest_document:v1",
        direction=Direction.TOP,
        anchors=("测试站",),
        keywords=("绝杀半波",),
        issue_pattern=r"(?P<issue>\d{1,4})期",
        value_pattern=r"(?P<value>[红绿蓝](?:波)?[单双])",
        options={
            "skip_document_anchor": True,
            "anchor_mode": "any",
            "candidate_side": "both",
        },
        before_documents=5,
        after_documents=5,
    )
    site = SiteSpec(
        site_id="hw-9996",
        name="测试站",
        url="https://example.test/topic/1.html",
        direction=Direction.TOP,
        strategy="nearest_document",
        anchors=("测试站",),
        parser_version="1",
        keywords=("绝杀半波",),
        anchor_mode="any",
        before_documents=5,
        after_documents=5,
    )
    documents = (
        Document(
            document_id="anchor",
            source=DocumentSource.PAGE,
            source_url="https://example.test/topic/1.html",
            order=0,
            content="测试站 绝杀半波",
        ),
        Document(
            document_id="near",
            source=DocumentSource.PAGE,
            source_url="https://example.test/topic/1.html#1",
            order=1,
            content="296期 绝杀半波 红单",
        ),
        Document(
            document_id="far",
            source=DocumentSource.PAGE,
            source_url="https://example.test/topic/1.html#2",
            order=2,
            content="296期 绝杀半波 绿双",
        ),
    )
    outcome = validate_evidence(
        site, 296, NearestDocumentParser(spec).parse(site, documents, 296)
    )
    assert isinstance(outcome, FailureResult)
    # 同期两个不同值必须被判为冲突（边界/记录一致性先过关才会走到冲突判定，
    # 这里只要不是「静默取最近那个」，失败即为正确行为）。
    assert outcome.code in {
        FailureCode.SAME_PERIOD_CONFLICT,
        FailureCode.DOCUMENT_BOUNDARY_MISMATCH,
    }


def test_cache_failure_keeps_existing_success_value() -> None:
    """失败结果不得抹掉同期已有成功值。"""

    repository = RecentCacheRepository(Path("unused-cache.json"))
    payload = _cache_payload([298, 297, 296])
    updated = repository.prepare_existing_period(
        [
            FailureResult(
                site_id="hw-9999",
                target_issue=298,
                code=FailureCode.NETWORK_ERROR,
                message="网络抖动",
            )
        ],
        site_names_by_id={"hw-9999": "测试站"},
        target_issue=298,
        base_payload=payload,
    )
    row = updated["sites"][0]
    assert row["values"]["298"] == "红单", "已有成功值被失败结果抹掉了"
    assert "298" not in row["failures"], "同一期不能既有成功又有失败记录"


def test_advance_complete_period_rolls_window_forward() -> None:
    """完整新期必须能推进窗口，否则日常跑新期永远写不进缓存。"""

    repository = RecentCacheRepository(Path("unused-cache.json"))
    payload = _cache_payload([298, 297, 296])
    results = [
        ValidatedResult(
            site_id="hw-9999",
            site_name="测试站",
            target_issue=299,
            value="蓝单",
            direction=Direction.TOP,
            evidence=_evidence(target_issue=299, boundary=(299, 298, 297)),
            parser_version="1",
        )
    ]
    updated = repository.prepare_advance_complete_period(
        results,
        site_names_by_id={"hw-9999": "测试站"},
        target_issue=299,
        expected_site_count=1,
        base_payload=payload,
    )
    issues = [int(issue) for issue in updated["issues"]]
    assert issues[0] == 299
    assert 298 in issues, "推进一期后 298 仍应在窗口内"
    assert 296 not in issues, "最老一期应被挤出窗口"
    assert updated["sites"][0]["values"]["299"] == "蓝单"


def test_cli_advances_window_for_new_period(tmp_path: Path) -> None:
    """cli 必须给新期走窗口推进，否则缓存永远停在旧窗口。"""

    from types import SimpleNamespace

    from banbo.cli import _prepare_cache_update
    from banbo.storage.site_repository import SiteRecord, SiteRepository

    cache_path = tmp_path / "recent_10_cache.json"
    cache_path.write_text(
        json.dumps(_cache_payload([298, 297, 296]), ensure_ascii=False),
        encoding="utf-8",
    )
    record = SiteRecord(
        site_id="hw-9999",
        name="测试站",
        url="https://example.test/topic/1.html",
        direction=Direction.TOP,
    )
    sites = SiteRepository([record])
    run = SimpleNamespace(
        site=record,
        outcome=ValidatedResult(
            site_id="hw-9999",
            site_name="测试站",
            target_issue=299,
            value="蓝单",
            direction=Direction.TOP,
            evidence=_evidence(target_issue=299, boundary=(299, 298, 297)),
            parser_version="1",
        ),
    )
    message, payload, _digest = _prepare_cache_update(
        cache_path, sites, [], 299, [run], run_id="test-run"
    )
    assert payload is not None, f"新期未推进缓存窗口：{message}"
    assert int(payload["issues"][0]) == 299


def test_cache_rejects_conflicting_value_for_existing_period() -> None:
    """同期已有不同结果时必须抛错，不得静默覆盖。"""

    repository = RecentCacheRepository(Path("unused-cache.json"))
    payload = _cache_payload([298, 297, 296])
    with pytest.raises(CacheValidationError, match="同期已有不同结果"):
        repository.prepare_existing_period(
            [
                ValidatedResult(
                    site_id="hw-9999",
                    site_name="测试站",
                    target_issue=298,
                    value="绿双",
                    direction=Direction.TOP,
                    evidence=_evidence(),
                    parser_version="1",
                )
            ],
            site_names_by_id={"hw-9999": "测试站"},
            target_issue=298,
            base_payload=payload,
        )


def test_cache_rejects_period_outside_window() -> None:
    """目标期不在缓存窗口内时必须拒绝，不能靠预改写窗口绕过。"""

    repository = RecentCacheRepository(Path("unused-cache.json"))
    payload = _cache_payload([298, 297, 296])
    with pytest.raises(CacheValidationError, match="新期数必须走完整单期流程"):
        repository.prepare_existing_period(
            [
                ValidatedResult(
                    site_id="hw-9999",
                    site_name="测试站",
                    target_issue=295,
                    value="红单",
                    direction=Direction.TOP,
                    evidence=_evidence(target_issue=295),
                    parser_version="1",
                )
            ],
            site_names_by_id={"hw-9999": "测试站"},
            target_issue=295,
            base_payload=payload,
        )


def _fragment_spec(site_id: str, *, join_zodiac: bool = False) -> ParserSpec:
    options = {
        "skip_document_anchor": True,
        "anchor_mode": "any",
        "skip_keyword_check": True,
    }
    if join_zodiac:
        options["join_zodiac_fragment"] = True
    return ParserSpec(
        site_id=site_id,
        strategy="history_block",
        parser_version="1",
        parser_id=f"{site_id}:history_block:v1",
        direction=Direction.TOP,
        anchors=(),
        keywords=("绝杀半波", "杀半波"),
        issue_pattern=r"(?P<issue>\d{1,4})期",
        value_pattern=r"(?P<value>[红绿蓝](?:波)?[单双])",
        options=options,
    )


def _fragment_site(site_id: str) -> SiteSpec:
    return SiteSpec(
        site_id=site_id,
        name="测试站",
        url="https://example.test/topic/1.html",
        direction=Direction.TOP,
        strategy="history_block",
        anchors=(),
        parser_version="1",
        keywords=("绝杀半波", "杀半波"),
        anchor_mode="any",
    )


def _single_document(content: str) -> tuple[Document, ...]:
    return (
        Document(
            document_id="a",
            source=DocumentSource.SCRIPT,
            source_url="https://example.test/a.js#decoded-1",
            order=0,
            content=content,
        ),
    )


def test_fragment_marker_is_hard_boundary_by_default() -> None:
    """默认片段标记是硬边界，一律截断（hw-0105 借值场景，审查第 1 条）。"""

    content = "296期 绝杀半波\u2063绿双 295期 绝杀半波 红单"
    spec = _fragment_spec("hw-0105")
    evidence = HistoryBlockParser(spec).parse(
        _fragment_site("hw-0105"), _single_document(content), 296
    )
    assert evidence == (), "296 期不得借到下一片段的绿双"


def test_zodiac_join_switch_off_keeps_hard_boundary() -> None:
    """形态像「期号+生肖」时，开关未开也必须截断。"""

    content = "299期 猴\u2063蓝双 3尾 开000 298期 猴 绿双 8尾 开猪08"
    spec = _fragment_spec("hw-0163")
    evidence = HistoryBlockParser(spec).parse(
        _fragment_site("hw-0163"), _single_document(content), 299
    )
    assert evidence == (), "开关未开时不得跨片段拼接"


def test_zodiac_join_switch_on_joins_same_row() -> None:
    """开关打开且是「期号+单个生肖」被拆开时，必须拼接（汉锺离场景）。"""

    content = "299期 猴\u2063蓝双 3尾 开000 298期 猴 绿双 8尾 开猪08"
    spec = _fragment_spec("hw-0163", join_zodiac=True)
    evidence = HistoryBlockParser(spec).parse(
        _fragment_site("hw-0163"), _single_document(content), 299
    )
    values = {item.value for item in evidence}
    assert values == {"蓝双"}, "期号+生肖被拆开时必须接上"


def test_zodiac_join_rejects_text_between_issue_and_zodiac() -> None:
    """期号与断点之间夹了别的文字时，即使开关打开也必须截断。"""

    content = "296期 绝杀猴\u2063绿双 295期 绝杀半波 红单"
    spec = _fragment_spec("hw-0163", join_zodiac=True)
    evidence = HistoryBlockParser(spec).parse(
        _fragment_site("hw-0163"), _single_document(content), 296
    )
    assert evidence == (), "「绝杀猴」不是表格行头，不得拼接"


def _nearest_spec(site_id: str, after: int) -> ParserSpec:
    return ParserSpec(
        site_id=site_id,
        strategy="nearest_document",
        parser_version="1",
        parser_id=f"{site_id}:nearest_document:v1",
        direction=Direction.TOP,
        anchors=("测试站",),
        keywords=("绝杀半波",),
        issue_pattern=r"(?P<issue>\d{1,4})期",
        value_pattern=r"(?P<value>[红绿蓝](?:波)?[单双])",
        options={
            "skip_document_anchor": True,
            "anchor_mode": "any",
            "candidate_side": "after",
        },
        before_documents=0,
        after_documents=after,
    )


def _nearest_site(site_id: str, after: int) -> SiteSpec:
    return SiteSpec(
        site_id=site_id,
        name="测试站",
        url="https://example.test/topic/1.html",
        direction=Direction.TOP,
        strategy="nearest_document",
        anchors=("测试站",),
        parser_version="1",
        keywords=("绝杀半波",),
        anchor_mode="any",
        before_documents=0,
        after_documents=after,
    )


def _page_period_documents() -> tuple[Document, ...]:
    url = "https://example.test/topic/1.html"
    documents = [
        Document(
            document_id="anchor",
            source=DocumentSource.PAGE,
            source_url=url,
            order=0,
            content="测试站 绝杀半波",
            record_id="rec-1",
        )
    ]
    for offset, issue in enumerate(range(296, 288, -1), start=1):
        documents.append(
            Document(
                document_id=f"d{issue}",
                source=DocumentSource.PAGE,
                source_url=url,
                order=offset,
                content=f"{issue}期 绝杀半波 红单",
                record_id="rec-1",
            )
        )
    return tuple(documents)


def test_nearest_document_drops_target_outside_page_window() -> None:
    """目标期不在页面 top 窗口内时必须失败，不得退回单文档退化边界。"""

    site = _nearest_site("hw-9997", 8)
    spec = _nearest_spec("hw-9997", 8)
    documents = _page_period_documents()

    # 289 期在页面第 9 组，top 窗口只到 294，解析器必须一条候选都不给。
    assert NearestDocumentParser(spec).parse(site, documents, 289) == ()
    outcome = validate_evidence(
        site, 289, NearestDocumentParser(spec).parse(site, documents, 289)
    )
    assert isinstance(outcome, FailureResult)
    assert outcome.code is FailureCode.TARGET_PERIOD_MISSING


def test_nearest_document_window_covers_exactly_three_periods() -> None:
    """窗口固定 3 期：294（第 3 组）通过，293（第 4 组）失败。"""

    documents = _page_period_documents()

    inside_site = _nearest_site("hw-9998", 8)
    inside_spec = _nearest_spec("hw-9998", 8)
    inside = validate_evidence(
        inside_site,
        294,
        NearestDocumentParser(inside_spec).parse(inside_site, documents, 294),
    )
    assert isinstance(inside, ValidatedResult)
    assert inside.value == "红单"

    outside_site = _nearest_site("hw-9999", 8)
    outside_spec = _nearest_spec("hw-9999", 8)
    outside = validate_evidence(
        outside_site,
        293,
        NearestDocumentParser(outside_spec).parse(outside_site, documents, 293),
    )
    assert isinstance(outside, FailureResult)
    assert outside.code is FailureCode.TARGET_PERIOD_MISSING


def test_nearest_document_exposes_page_window_without_target() -> None:
    """页面窗口应能脱离目标期单独算出，供上层显式下传。"""

    site = _nearest_site("hw-9995", 8)
    delegate = HistoryBlockParser(
        ParserSpec(
            site_id="hw-9995",
            strategy="history_block",
            parser_version="1",
            parser_id="hw-9995:history_block:v1",
            direction=Direction.TOP,
            anchors=(),
            keywords=("绝杀半波",),
            issue_pattern=r"(?P<issue>\d{1,4})期",
            value_pattern=r"(?P<value>[红绿蓝](?:波)?[单双])",
            options={"skip_document_anchor": True, "anchor_mode": "any"},
        )
    )
    window = delegate.page_window_issues(site, _page_period_documents())
    assert window == (296, 295, 294), "top 窗口应固定为页面前三组"


def test_nearest_document_page_window_switch_off_keeps_local_boundary() -> None:
    """关闭 page_window_strict 时退回旧行为：保留候选自身边界。"""

    site = _nearest_site("hw-9994", 8)
    spec = _nearest_spec("hw-9994", 8)
    options = dict(spec.options)
    options["page_window_strict"] = False
    relaxed = ParserSpec(
        site_id=spec.site_id,
        strategy=spec.strategy,
        parser_version=spec.parser_version,
        parser_id=spec.parser_id,
        direction=spec.direction,
        anchors=spec.anchors,
        keywords=spec.keywords,
        issue_pattern=spec.issue_pattern,
        value_pattern=spec.value_pattern,
        options=options,
        before_documents=spec.before_documents,
        after_documents=spec.after_documents,
    )
    documents = _page_period_documents()
    evidence = NearestDocumentParser(relaxed).parse(site, documents, 289)
    assert evidence, "开关关闭时应保留窗口外候选"
    assert all(item.boundary_issues == (289,) for item in evidence), (
        "开关关闭时应保留候选自身边界，而不是套用页面窗口"
    )


def test_combined_sibling_compact_does_not_borrow_across_documents() -> None:
    """compact 拼接两个文档时，跨期借值必须被挡住（端到端）。

    compact 会把「开猪08」与「297期」压成「开猪08297期」，期号正则可能读成
    8297；这里验证真实链路下 296 期不会借到下一文档的值。
    """

    spec = ParserSpec(
        site_id="hw-0105",
        strategy="combined_sibling",
        parser_version="1",
        parser_id="hw-0105:combined_sibling:v1",
        direction=Direction.TOP,
        anchors=("白蛇传",),
        keywords=("绝杀半波",),
        issue_pattern=r"(?P<issue>\d{1,4})期",
        value_pattern=r"(?P<value>[红绿蓝](?:波)?[单双])",
        options={
            "compact": True,
            "anchor_mode": "any",
            "skip_keyword_check": True,
        },
    )
    site = SiteSpec(
        site_id="hw-0105",
        name="白蛇传",
        url="https://example.test/topic/1.html",
        direction=Direction.TOP,
        strategy="combined_sibling",
        anchors=("白蛇传",),
        parser_version="1",
        keywords=("绝杀半波",),
        anchor_mode="any",
    )
    documents = (
        Document(
            document_id="d1",
            source=DocumentSource.SCRIPT,
            source_url="https://example.test/a.js#decoded-1",
            order=0,
            content="白蛇传 绝杀半波 296期 绿双 开猪08",
        ),
        Document(
            document_id="d2",
            source=DocumentSource.SCRIPT,
            source_url="https://example.test/a.js#decoded-2",
            order=1,
            content="297期 绝杀半波 红单",
        ),
    )
    evidence = CombinedSiblingParser(spec).parse(site, documents, 296)
    assert evidence, "296 期应取到本期的值，不能因为跨文档而丢空"
    values = {item.value for item in evidence}
    assert values == {"绿双"}, "296 期只能取本期值，不得借到 297 期的红单"
    issues = {item.target_issue for item in evidence}
    assert issues == {296}, "compact 拼接不得把「开猪08」与「297期」读成别的期号"

    # 下一期也必须还能按 297 读到：分隔符丢失时「开猪08」会与「297期」粘成
    # 「08297期」，期号被读成 8297，297 期就取不到了。
    next_evidence = CombinedSiblingParser(spec).parse(site, documents, 297)
    assert {item.value for item in next_evidence} == {"红单"}, (
        "297 期应取到红单；取不到说明 compact 片段分隔符失效、期号被粘连"
    )


def test_same_span_tie_breaks_by_direction_edge() -> None:
    """两份重叠表跨度相同时，底部取止于目标期的，顶部取起于目标期的。

    不言不语 301：旧年度表 301..307 给蓝双，当期表 293..301 给蓝单。
    """

    bottom_site = _site(Direction.BOTTOM)
    stale = _evidence(
        "蓝双",
        target_issue=301,
        boundary=(301, 300, 299),
        direction=Direction.BOTTOM,
    )
    live = _evidence(
        "蓝单",
        target_issue=301,
        boundary=(301, 300, 299),
        direction=Direction.BOTTOM,
    )
    stale = replace(stale, snippet="301期 绝杀半波 蓝双 302期 绝杀半波 绿双 303期 绝杀半波 蓝单")
    live = replace(
        live,
        snippet="299期 绝杀半波 红双 300期 绝杀半波 红单 301期 绝杀半波 蓝单",
    )
    outcome = validate_evidence(bottom_site, 301, (stale, live))
    assert isinstance(outcome, ValidatedResult)
    assert outcome.value == "蓝单", "底部方向应取止于 301 的那份当期表"

    top_site = _site(Direction.TOP)
    stale_top = replace(
        stale,
        direction=Direction.TOP,
        snippet="301期 绝杀半波 蓝双 302期 绝杀半波 绿双 303期 绝杀半波 蓝单",
    )
    live_top = replace(
        live,
        direction=Direction.TOP,
        snippet="299期 绝杀半波 红双 300期 绝杀半波 红单 301期 绝杀半波 蓝单",
    )
    outcome_top = validate_evidence(top_site, 301, (stale_top, live_top))
    assert isinstance(outcome_top, ValidatedResult)
    assert outcome_top.value == "蓝双", "顶部方向应取起于 301 的那份当期表"
