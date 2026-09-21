from banbo.application.single_period import build_site_spec
from banbo.cli import _load_runtime, _prepare_cache_update
from banbo.domain import Document, DocumentSource, ValidatedResult
from banbo.fetch.http_client import HttpClient
from banbo.parsers import build_default_registry


def test_declared_gbk_is_preferred_over_http_iso8859_label():
    content = '<meta charset="gbk">天地空间'.encode("gb18030")
    assert "天地空间" in HttpClient._decode(content, "ISO-8859-1")


def test_tiandi_space_bottom_265_uses_latest_three_records(tmp_path):
    sites, specs, _ = _load_runtime()
    site_record = sites.get("hw-0205")
    parser_spec = next(item for item in specs if item.site_id == "hw-0205")
    site = build_site_spec(site_record, parser_spec)
    registry = build_default_registry()
    registry.bind(parser_spec)
    document = Document(
        document_id="repair-265",
        source=DocumentSource.PAGE,
        source_url=site_record.url,
        order=0,
        content=(
            "天地空间 263期绝杀半波『绿单』开:狗09准 "
            "264期绝杀半波『绿单』开:狗21准 "
            "265期绝杀半波『绿单』开:狗00准"
        ),
    )
    outcome = __import__("banbo.domain.validation", fromlist=["validate_evidence"]).validate_evidence(
        site, 265, registry.parse(site, (document,), 265)
    )
    assert isinstance(outcome, ValidatedResult)
    assert outcome.value == "绿单"

    class Run:
        def __init__(self, result):
            self.outcome = result

    payload = _prepare_cache_update(
        tmp_path / "recent_10_cache.json",
        sites,
        specs,
        265,
        [Run(outcome)],
        run_id="test-265",
    )[1]
    assert payload["window_size"] == 10
    assert payload["issues"] == list(range(265, 255, -1))
