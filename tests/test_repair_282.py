"""282 期修复回归：一清二白(hw-0050) title_neighbor 邻居窗口需覆盖第 18 个后续片段。

站方持续追加 decoded 片段，282 期值文档落在锚点后第 18 个文档位；
after_documents=16 的旧窗口会把它顶出，必须按本家族惯例放宽到 32
（与 271 期 hw-0059/hw-0148、274 期 hw-0158 同一形态）。
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

SITE_ID = "hw-0050"
SCRIPT_URL = "https://example.test/upload/script/10/repair282.js"
ANCHOR_TEXT = "282期 〖一清二白〗 绝杀半波"
VALUE_TEXT = (
    "280期:绝杀半波 绿单 开龙15准 "
    "281期:绝杀半波 绿双 开鸡10准 "
    "282期:绝杀半波 红单 开0000准"
)


def _document(order: int, content: str) -> Document:
    return Document(
        document_id=f"repair-282-{order}",
        source=DocumentSource.SCRIPT,
        source_url=f"{SCRIPT_URL}#decoded-{order}",
        order=order,
        content=content,
    )


def _documents() -> tuple[Document, ...]:
    return tuple(
        [_document(0, ANCHOR_TEXT)]
        + [_document(order, "布局片段") for order in range(1, 19)]
        + [_document(19, VALUE_TEXT)]
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


def test_hw0050_reaches_value_document_eighteen_slots_after_anchor():
    site, registry = _runtime()
    assert site.after_documents == 32
    outcome = validate_evidence(
        site, 282, registry.parse(site, _documents(), 282)
    )
    assert isinstance(outcome, ValidatedResult)
    assert outcome.value == "红单"
    assert outcome.evidence.boundary_issues == (280, 281, 282)
    assert outcome.evidence.document_order == 19


def test_hw0050_old_window_of_sixteen_would_have_dropped_target_282():
    """回归根因：旧 after_documents=16 的窗口到不了第 18 个后续文档。"""

    site, registry = _runtime(after_documents=16)
    outcome = validate_evidence(
        site, 282, registry.parse(site, _documents(), 282)
    )
    assert isinstance(outcome, FailureResult)
    assert outcome.code.value == "target_period_missing"


def test_hw0050_neighbor_281_is_inside_the_same_window():
    site, registry = _runtime()
    outcome = validate_evidence(
        site, 281, registry.parse(site, _documents(), 281)
    )
    assert isinstance(outcome, ValidatedResult)
    assert outcome.value == "绿双"


def test_hw0050_absent_period_283_still_fails():
    site, registry = _runtime()
    outcome = validate_evidence(
        site, 283, registry.parse(site, _documents(), 283)
    )
    assert isinstance(outcome, FailureResult)
    assert outcome.code.value == "target_period_missing"
