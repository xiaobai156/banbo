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

    # 建缓存基准必须全站结果（子集跑不再允许种下部分基准）。
    # hw-0205 已封存，不进正式站点集合，所以这里用全部在用站点的占位结果
    # 凑齐全站，只为验证窗口形状。
    runs = []
    for other in sites.all():
        if other.archived:
            continue
        runs.append(
            Run(
                ValidatedResult(
                    site_id=other.site_id,
                    site_name=other.name,
                    target_issue=265,
                    value="红单",
                    direction=other.direction,
                    evidence=outcome.evidence,
                    parser_version="test-265",
                )
            )
        )

    payload = _prepare_cache_update(
        tmp_path / "recent_10_cache.json",
        sites,
        specs,
        265,
        runs,
        run_id="test-265",
    )[1]
    assert payload["window_size"] == 10
    assert payload["issues"] == list(range(265, 255, -1))


def test_partial_run_refuses_to_create_a_cache_baseline(tmp_path):
    sites, specs, _ = _load_runtime()
    site_record = sites.get("hw-0205")
    outcome = ValidatedResult(
        site_id=site_record.site_id,
        site_name=site_record.name,
        target_issue=265,
        value="红单",
        direction=site_record.direction,
        evidence=None,  # 本用例只关心缓存闸门
        parser_version="test-265",
    )

    class Run:
        def __init__(self, result):
            self.outcome = result

    try:
        _prepare_cache_update(
            tmp_path / "recent_10_cache.json",
            sites,
            specs,
            265,
            [Run(outcome)],
            run_id="test-265-partial",
        )
    except ValueError as exc:
        assert "建基准必须跑全站" in str(exc)
    else:
        raise AssertionError("子集跑不应该建立缓存基准")
    assert not (tmp_path / "recent_10_cache.json").exists()
