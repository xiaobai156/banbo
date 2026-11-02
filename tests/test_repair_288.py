"""288 期修复回归：老奇人(hw-0042) 当期行号与「期」字被站方拆进两个元素。

站方 288 期把这期行首写成 `<span>288</span><span>期 绝杀半波【红波单】开000准</span>`，
`html_to_text` 把标签替换成换行、`normalize_text` 再收成空格，
于是文本里出现 `288 期`；旧 issue_pattern `(\\d{1,4})期` 要求数字与「期」紧邻，
288 行整体不成立 ⇒ 当期候选为 0（只认到 287/286/285）⇒
direction=top 取前三组 (287,286,285)，当期被挤出 ⇒ target_period_missing。

修复：站点级 issue_pattern 允许数字与「期」之间空白
`(?P<issue>\\d{1,4})\\s*期`（JSON 里写 `\\s`），
parser_version 2→3、parser_id 升为 hw-0042:decoded_sibling:v3。
取值仍由 normalize_half_wave 归一（红波单 → 红单）。
"""

from dataclasses import replace

from banbo.application.single_period import build_site_spec
from banbo.cli import _load_runtime
from banbo.domain import (
    Document,
    DocumentSource,
    FailureResult,
    ValidatedResult,
    validate_evidence,
)
from banbo.parsers import build_default_registry

SITE_ID = "hw-0042"
SCRIPT_URL = "https://example.test/upload/script/10/repair288.js"
ANCHOR_TEXT = "288期 老奇人 绝杀半波 已公开"
# 288 行的数字与「期」被 <span> 拆开（真实页面形态），287 及以下仍是连写。
VALUE_TEXT = (
    "<p><span>288</span><span>期 绝杀半波【红波单】开000准</span></p>"
    "<p><span>287期 绝杀半波【蓝波单】开猪08准</span></p>"
    "<p><span>286期 绝杀半波【蓝波双】开羊24准</span></p>"
    "<p><span>285期 绝杀半波【绿波双】开鼠19准</span></p>"
)
OLD_ISSUE_PATTERN = "(?P<issue>\\d{1,4})期"


def _document(order: int, content: str) -> Document:
    return Document(
        document_id=f"repair-288-{order}",
        source=DocumentSource.SCRIPT,
        source_url=f"{SCRIPT_URL}#decoded-{order}",
        order=order,
        content=content,
    )


def _documents() -> tuple[Document, ...]:
    return (
        _document(0, ANCHOR_TEXT),
        _document(1, VALUE_TEXT),
        _document(2, "布局片段"),
    )


def _runtime(issue_pattern: str | None = None):
    sites, specs, _ = _load_runtime()
    record = sites.get(SITE_ID)
    spec = next(item for item in specs if item.site_id == SITE_ID)
    if issue_pattern is not None:
        spec = replace(spec, issue_pattern=issue_pattern)
    site = build_site_spec(record, spec)
    registry = build_default_registry()
    registry.bind(spec)
    return site, registry


def test_hw0042_reaches_spaced_issue_for_288():
    site, registry = _runtime()
    assert "\\s*" in site.issue_pattern
    outcome = validate_evidence(
        site, 288, registry.parse(site, _documents(), 288)
    )
    assert isinstance(outcome, ValidatedResult)
    assert outcome.value == "红单"
    assert outcome.evidence.boundary_issues == (288, 287, 286)
    assert outcome.evidence.document_order == 1


def test_hw0042_old_pattern_would_have_dropped_target_288():
    """回归根因：数字与「期」之间有空白时旧 pattern 认不出当期行。"""

    site, registry = _runtime(issue_pattern=OLD_ISSUE_PATTERN)
    outcome = validate_evidence(
        site, 288, registry.parse(site, _documents(), 288)
    )
    assert isinstance(outcome, FailureResult)
    assert outcome.code.value == "target_period_missing"


def test_hw0042_neighbor_287_is_unaffected():
    site, registry = _runtime()
    outcome = validate_evidence(
        site, 287, registry.parse(site, _documents(), 287)
    )
    assert isinstance(outcome, ValidatedResult)
    assert outcome.value == "蓝单"
    assert outcome.evidence.boundary_issues == (288, 287, 286)


def test_hw0042_absent_period_289_still_fails():
    site, registry = _runtime()
    outcome = validate_evidence(
        site, 289, registry.parse(site, _documents(), 289)
    )
    assert isinstance(outcome, FailureResult)
    assert outcome.code.value == "target_period_missing"
