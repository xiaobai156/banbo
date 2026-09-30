from banbo.application.single_period import build_site_spec
from banbo.cli import _load_runtime
from banbo.domain import Document, DocumentSource, ValidatedResult
from banbo.domain.validation import validate_evidence
from banbo.parsers import build_default_registry


def _tianji_outcome(issue: int):
    sites, specs, _ = _load_runtime()
    site_record = sites.get("hw-0097")
    spec = next(item for item in specs if item.site_id == "hw-0097")
    site = build_site_spec(site_record, spec)
    document = Document(
        document_id="tianji-248",
        source=DocumentSource.PAGE,
        source_url=site_record.url,
        order=0,
        content=(
            "248期:【绝杀一波】 作者:天机老人 "
            "248期:※绝杀一波※【绿单】开??准 "
            "247期:※绝杀一波※【红双】开40兔错 "
            "246期:※绝杀一波※【蓝双】开30牛准 "
            "245期:※绝杀一波※【绿双】开18牛准"
        ),
    )
    registry = build_default_registry()
    registry.bind(spec)
    return validate_evidence(site, issue, registry.parse(site, (document,), issue))


def test_tianji_uses_nonempty_canonical_article_url():
    sites, _, _ = _load_runtime()
    assert sites.get("hw-0097").url == "https://mm.737799b.com:1888/art_gsb/8161/"


def test_tianji_top_window_and_missing_period():
    assert _tianji_outcome(248).value == "绿单"
    assert _tianji_outcome(247).value == "红双"
    assert _tianji_outcome(246).value == "蓝双"
    assert not isinstance(_tianji_outcome(245), ValidatedResult)
    assert not isinstance(_tianji_outcome(249), ValidatedResult)
