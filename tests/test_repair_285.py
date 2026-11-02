"""285 期修复回归：天上地下(hw-0088) 当期值被站方拆成两个元素，值 token 带空格。

站方 285 期把这期半波值写成 `【<span>红</span><span>单</span>】`，
`html_to_text` 把标签替换成换行、`normalize_text` 再收成空格，
于是文本里出现 `红 单`；旧 value_pattern `[红绿蓝](?:波)?[单双]`
要求颜色与单双紧邻，匹配不到 ⇒ 当期候选为 0 ⇒ target_period_missing。
修复：站点级 value_pattern 允许值内部空白
`(?P<value>[红绿蓝]\\s*(?:波)?\\s*[单双])`，
取值仍由 normalize_half_wave 去掉空格后校验（红 单 → 红单）。
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

SITE_ID = "hw-0088"
SCRIPT_URL = "https://example.test/upload/script/10/repair285.js"
ANCHOR_TEXT = "天上地下•绝杀半波"
VALUE_TEXT = (
    "283期 绝杀半波 蓝单 开:牛18准 "
    "284期 绝杀半波 绿单 开:猪32准 "
    "285期 绝杀半波 红 单 开:?00准"
)
OLD_VALUE_PATTERN = "(?P<value>[红绿蓝](?:波)?[单双])"


def _document(order: int, content: str) -> Document:
    return Document(
        document_id=f"repair-285-{order}",
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
        _document(3, "布局片段"),
    )


def _runtime(value_pattern: str | None = None):
    sites, specs, _ = _load_runtime()
    record = sites.get(SITE_ID)
    spec = next(item for item in specs if item.site_id == SITE_ID)
    if value_pattern is not None:
        spec = replace(spec, value_pattern=value_pattern)
    site = build_site_spec(record, spec)
    registry = build_default_registry()
    registry.bind(spec)
    return site, registry


def test_hw0088_reaches_spaced_value_for_285():
    site, registry = _runtime()
    assert "\\s*" in site.value_pattern
    outcome = validate_evidence(
        site, 285, registry.parse(site, _documents(), 285)
    )
    assert isinstance(outcome, ValidatedResult)
    assert outcome.value == "红单"
    assert outcome.evidence.boundary_issues == (283, 284, 285)
    assert outcome.evidence.document_order == 1


def test_hw0088_old_pattern_would_have_dropped_target_285():
    """回归根因：值 token 带空格时旧 pattern 匹配不到，当期无候选。"""

    site, registry = _runtime(value_pattern=OLD_VALUE_PATTERN)
    outcome = validate_evidence(
        site, 285, registry.parse(site, _documents(), 285)
    )
    assert isinstance(outcome, FailureResult)
    assert outcome.code.value == "target_period_missing"


def test_hw0088_neighbor_284_is_unaffected():
    site, registry = _runtime()
    outcome = validate_evidence(
        site, 284, registry.parse(site, _documents(), 284)
    )
    assert isinstance(outcome, ValidatedResult)
    assert outcome.value == "绿单"


def test_hw0088_absent_period_286_still_fails():
    site, registry = _runtime()
    outcome = validate_evidence(
        site, 286, registry.parse(site, _documents(), 286)
    )
    assert isinstance(outcome, FailureResult)
    assert outcome.code.value == "target_period_missing"
