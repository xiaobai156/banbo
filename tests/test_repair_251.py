from banbo.application.single_period import build_site_spec
from banbo.cli import _load_runtime
from banbo.domain import Document, DocumentSource, ValidatedResult
from banbo.domain.validation import validate_evidence
from banbo.parsers import build_default_registry


def _document(order: int, content: str) -> Document:
    return Document(
        document_id=f"repair-251-{order}",
        source=DocumentSource.SCRIPT,
        source_url=(
            "https://example.test/upload/script/09/repair.js"
            f"#decoded-{order}"
        ),
        order=order,
        content=content,
    )


def _outcome(site_id: str, documents: tuple[Document, ...], issue: int = 251):
    sites, specs, _ = _load_runtime()
    site_record = sites.get(site_id)
    parser_spec = next(item for item in specs if item.site_id == site_id)
    site = build_site_spec(site_record, parser_spec)
    registry = build_default_registry()
    registry.bind(parser_spec)
    return validate_evidence(
        site,
        issue,
        registry.parse(site, documents, issue),
    )


def test_title_neighbor_reaches_split_251_row_for_langu_wujia():
    documents = tuple(
        [_document(0, "浪女无家 251期绝杀半波")]
        + [_document(order, "布局片段") for order in range(1, 6)]
        + [
            _document(6, "249期绝杀半波【红波单】"),
            _document(7, "250期绝杀半波【蓝波双】"),
            _document(8, "251期绝杀半波【绿波单】"),
        ]
    )
    outcome = _outcome("hw-0059", documents)
    assert isinstance(outcome, ValidatedResult)
    assert outcome.value == "绿单"


def test_shouzhu_selects_target_block_before_later_history_block():
    documents = (
        _document(0, "251期: 守株待兔「精杀半波」"),
        _document(
            1,
            "246期「精杀半波」【绿波单】"
            "247期「精杀半波」【绿波双】"
            "248期「精杀半波」【蓝波双】"
            "249期「精杀半波」【红波单】"
            "250期「精杀半波」【红波双】"
            "251期「精杀半波」【蓝波双】",
        ),
        _document(2, "247期「精杀半波」【绿波双】"),
        _document(3, "248期「精杀半波」【蓝波双】"),
        _document(4, "249期「精杀半波」【红波单】"),
        _document(5, "250期「精杀半波」【红波双】"),
        _document(6, "上一篇 下一篇"),
    )
    outcome = _outcome("hw-0141", documents)
    assert isinstance(outcome, ValidatedResult)
    assert outcome.value == "蓝双"

