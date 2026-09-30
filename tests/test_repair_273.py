"""273 期修复回归：切中时弊(hw-0159) 文章列表改为“最新期在前”后的方向窗口。

站方把「绝杀半波」列表从旧→新改成新→旧；当片段累积到 4 期时，
bottom 窗口只取末尾 3 组会把最新期排出窗口，必须按 top 窗口取最新三组。
"""

from dataclasses import replace

from banbo.application.single_period import build_site_spec
from banbo.cli import _load_runtime
from banbo.domain import (
    Direction,
    Document,
    DocumentSource,
    FailureResult,
    ValidatedResult,
    validate_evidence,
)
from banbo.parsers import build_default_registry

SITE_ID = "hw-0159"

# 273 期现场真实片段（节选自 decoded-3）：标题行 + 新→旧四行。
LIVE_FRAGMENT = (
    "特料帖 273期: 【绝杀半波】 作者:切中时弊 "
    "273期：绝杀半波（蓝双）开0000准 "
    "272期：绝杀半波（红双）开蛇02错 "
    "271期：绝杀半波（红双）开猴35准 "
    "270期：绝杀半波（绿双）开鼠19准"
)


def _runtime(direction: Direction | None = None):
    sites, specs, _ = _load_runtime()
    record = sites.get(SITE_ID)
    spec = next(item for item in specs if item.site_id == SITE_ID)
    site = build_site_spec(record, spec)
    if direction is not None:
        site = replace(site, direction=direction)
        spec = replace(spec, direction=direction)
    registry = build_default_registry()
    registry.bind(spec)
    return record, site, registry


def _document(record, content: str = LIVE_FRAGMENT) -> Document:
    return Document(
        document_id="repair-273",
        source=DocumentSource.PAGE,
        source_url=record.url,
        order=0,
        content=content,
    )


def test_hw0159_target_273_uses_top_window_of_newest_first_list():
    record, site, registry = _runtime()
    assert site.direction is Direction.TOP
    outcome = validate_evidence(
        site, 273, registry.parse(site, (_document(record),), 273)
    )
    assert isinstance(outcome, ValidatedResult)
    assert outcome.value == "蓝双"
    assert outcome.evidence.boundary_issues == (273, 272, 271)


def test_hw0159_neighbor_272_is_inside_same_top_window():
    record, site, registry = _runtime()
    outcome = validate_evidence(
        site, 272, registry.parse(site, (_document(record),), 272)
    )
    assert isinstance(outcome, ValidatedResult)
    assert outcome.value == "红双"
    assert outcome.evidence.boundary_issues == (273, 272, 271)


def test_hw0159_absent_period_274_still_fails():
    record, site, registry = _runtime()
    outcome = validate_evidence(
        site, 274, registry.parse(site, (_document(record),), 274)
    )
    assert isinstance(outcome, FailureResult)
    assert outcome.code.value == "target_period_missing"


def test_hw0159_old_bottom_window_would_have_dropped_target_273():
    """回归根因：底部窗口只取末尾三组，最新期会被排出窗口。"""

    record, site, registry = _runtime(direction=Direction.BOTTOM)
    outcome = validate_evidence(
        site, 273, registry.parse(site, (_document(record),), 273)
    )
    assert isinstance(outcome, FailureResult)
    assert outcome.code.value == "target_period_missing"


def test_hw0159_wrong_keyword_fragment_is_rejected():
    record, site, registry = _runtime()
    other = "特料帖 273期: 【稳杀半波】 作者:切中时弊 273期：稳杀半波（蓝双）开0000准"
    outcome = validate_evidence(
        site, 273, registry.parse(site, (_document(record, other),), 273)
    )
    assert isinstance(outcome, FailureResult)
