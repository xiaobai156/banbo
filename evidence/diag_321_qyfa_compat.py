# -*- coding: utf-8 -*-
"""只读：模拟给 hw-0001 加「绝杀一波」关键词后，多个期数的解析结果（不写配置/输出/缓存）。"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from banbo.application.single_period import build_site_spec  # noqa: E402
from banbo.fetch.document_discovery import DiscoveryOptions, DocumentDiscoverer  # noqa: E402
from banbo.fetch.http_client import HttpClient  # noqa: E402
from banbo.parsers import build_default_registry  # noqa: E402
from banbo.parsers.anchor_segment import AnchorSegmentParser  # noqa: E402
from banbo.parsers.specs import parse_parser_specs  # noqa: E402
from banbo.domain.validation import validate_evidence  # noqa: E402
from banbo.domain import ValidatedResult, FailureResult  # noqa: E402
from banbo.storage.site_repository import SiteRepository  # noqa: E402

SITE_ID = "hw-0001"
PERIODS = [int(x) for x in (sys.argv[1:] or ["320", "319", "318", "312", "311"])]

sites = SiteRepository.from_json(ROOT / "config" / "sites.json")
specs = list(parse_parser_specs(json.loads((ROOT / "config" / "parser_specs.json").read_text(encoding="utf-8"))))
record = next(s for s in sites.all() if s.site_id == SITE_ID)
spec = next(s for s in specs if s.site_id == SITE_ID)
site = build_site_spec(record, spec)
options = DiscoveryOptions(
    allowed_external_hosts=tuple(spec.options.get("allowed_external_hosts", ())),
    script_path_markers=("/upload/script/", "/template/tags/", "/tags/"),
    render_browser=bool(spec.options.get("render_browser", False)),
)
docs = DocumentDiscoverer(HttpClient(timeout=25, retries=2)).discover(
    site.url, options=options, record_id_pattern=spec.record_id_pattern or None
)
print("docs", len(docs))

base_kw = tuple(spec.keywords)
with_extra = base_kw + ("绝杀一波",)
cache = json.loads((ROOT / "recent_10_cache.json").read_text(encoding="utf-8"))
cached = next(s for s in cache["sites"] if s["url"] == site.url)

for kw_label, kws in (("现状(不含绝杀一波)", base_kw), ("加绝杀一波", with_extra)):
    print("\n===== %s =====" % kw_label)
    for period in PERIODS:
        spec2 = replace(spec, keywords=kws)
        site2 = replace(site, keywords=kws, expected_record_id=None)
        ev = AnchorSegmentParser(spec2).parse(site2, tuple(docs), period)
        outcome = validate_evidence(site2, period, ev)
        old = cached["values"].get(str(period))
        if isinstance(outcome, ValidatedResult):
            print("  %s -> OK value=%s boundary=%s cached=%s %s"
                  % (period, outcome.value, tuple(outcome.evidence.boundary_issues), old,
                     "一致" if old == outcome.value else "★不同"))
        else:
            print("  %s -> FAIL %s  cached=%s" % (period, outcome.code.value, old))
