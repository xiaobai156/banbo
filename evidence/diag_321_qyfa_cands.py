# -*- coding: utf-8 -*-
"""只读：加「绝杀一波」后打印每期候选数、冲突值与片段。"""
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
from banbo.parsers.anchor_segment import AnchorSegmentParser  # noqa: E402
from banbo.parsers.specs import parse_parser_specs  # noqa: E402
from banbo.storage.site_repository import SiteRepository  # noqa: E402

SITE_ID = "hw-0001"
PERIODS = [int(x) for x in (sys.argv[1:] or ["318", "319", "320"])]
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
kws = tuple(spec.keywords) + ("绝杀一波",)
spec2 = replace(spec, keywords=kws)
site2 = replace(site, keywords=kws)
for period in PERIODS:
    ev = AnchorSegmentParser(spec2).parse(site2, tuple(docs), period)
    print("\n%s 期：证据 %d 条" % (period, len(ev)))
    for e in ev:
        print("   value=%r cands=%s boundary=%s kw=%s conflict=%s"
              % (e.value, e.candidate_count, tuple(e.boundary_issues),
                 e.keyword_passed, tuple(e.conflict_values)))
        print("      snippet=%r" % (e.snippet[:160],))
