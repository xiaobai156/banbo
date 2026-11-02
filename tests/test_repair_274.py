"""274 期修复回归：破釜沈舟(hw-0158) title_neighbor 邻居窗口需覆盖第 17 个后续片段。

站方持续追加 decoded 片段，274 期值文档落在锚点后第 17 个文档位；
after_documents=16 的旧窗口会把它顶出，必须按本家族惯例放宽到 32。
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

SITE_ID = "hw-0158"
SCRIPT_URL = "https://example.test/upload/script/10/repair274.js"
ANCHOR_TEXT = "274期 绝杀半波 已公开 作者:破釜沈舟"
VALUE_TEXT = (
    "271期:◆绝杀半波◆ 红双 开猴35准 "
    "272期:◆绝杀半波◆ 绿双 开蛇02准 "
    "273期:◆绝杀半波◆ 蓝双 开虎05准 "
    "274期:◆绝杀半波◆ 绿双 开?00准"
)


def _document(order: int, content: str) -> Document:
    return Document(
        document_id=f"repair-274-{order}",
        source=DocumentSource.SCRIPT,
        source_url=f"{SCRIPT_URL}#decoded-{order}",
        order=order,
        content=content,
    )


def _documents() -> tuple[Document, ...]:
    return tuple(
        [_document(0, ANCHOR_TEXT)]
        + [_document(order, "布局片段") for order in range(1, 18)]
        + [_document(18, VALUE_TEXT)]
    )


def _runtime(after_documents: int | None = None):
    sites, specs, _ = _load_runtime()
    record = sites.get(SITE_ID)
    spec = next(item for item in specs if item.site_id == SITE_ID)
    if after_documents is not None:
        spec = replace(spec, after_documents=after_documents)
    site = build_site_spec(record, spec)
    registry = build_default_registry()
    registry.bind(spec)
    return site, registry


def test_hw0158_reaches_value_document_seventeen_slots_after_anchor():
    site, registry = _runtime()
    outcome = validate_evidence(
        site, 274, registry.parse(site, _documents(), 274)
    )
    assert isinstance(outcome, ValidatedResult)
    assert outcome.value == "绿双"
    assert outcome.evidence.boundary_issues == (272, 273, 274)
    assert outcome.evidence.document_order == 18


def test_hw0158_old_window_of_sixteen_would_have_dropped_target_274():
    """回归根因：旧 after_documents=16 的窗口到不了第 17 个后续文档。"""

    site, registry = _runtime(after_documents=16)
    outcome = validate_evidence(
        site, 274, registry.parse(site, _documents(), 274)
    )
    assert isinstance(outcome, FailureResult)
    assert outcome.code.value == "target_period_missing"


def test_hw0158_neighbor_273_is_inside_the_same_window():
    site, registry = _runtime()
    outcome = validate_evidence(
        site, 273, registry.parse(site, _documents(), 273)
    )
    assert isinstance(outcome, ValidatedResult)
    assert outcome.value == "蓝双"


def test_hw0158_absent_period_275_still_fails():
    site, registry = _runtime()
    outcome = validate_evidence(
        site, 275, registry.parse(site, _documents(), 275)
    )
    assert isinstance(outcome, FailureResult)
    assert outcome.code.value == "target_period_missing"
