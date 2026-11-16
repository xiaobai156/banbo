# -*- coding: utf-8 -*-
"""只读：直接调用 hw-0052 的解析器，打印全部候选证据。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from banbo.application.single_period import build_site_spec  # noqa: E402
from banbo.fetch.document_discovery import DiscoveryOptions, DocumentDiscoverer  # noqa: E402
from banbo.fetch.http_client import HttpClient  # noqa: E402
from banbo.parsers import build_default_registry  # noqa: E402
from banbo.parsers.specs import parse_parser_specs  # noqa: E402
from banbo.storage.site_repository import SiteRepository  # noqa: E402

site_id = sys.argv[1]
period = int(sys.argv[2])
sites = SiteRepository.from_json(ROOT / "config" / "sites.json")
specs = list(parse_parser_specs(json.loads((ROOT / "config" / "parser_specs.json").read_text(encoding="utf-8"))))
record = next(s for s in sites.all() if s.site_id == site_id)
spec = next(s for s in specs if s.site_id == site_id)
site = build_site_spec(record, spec)
options = DiscoveryOptions(
    allowed_external_hosts=tuple(spec.options.get("allowed_external_hosts", ())),
    script_path_markers=("/upload/script/", "/template/tags/", "/tags/"),
    render_browser=bool(spec.options.get("render_browser", False)),
)
docs = DocumentDiscoverer(HttpClient(timeout=25, retries=2)).discover(
    site.url, options=options, record_id_pattern=spec.record_id_pattern or None
)
registry = build_default_registry()
registry.bind(spec)
parser = registry.parser_for(site_id)
ev = parser.parse(site, tuple(docs), period)
print("docs", len(docs), "strategy", spec.strategy, "evidence", len(ev))
for e in ev:
    print("  value=%r order=%s src=%s cands=%s boundary=%s anchor=%s kw=%s same=%s rel=%s"
          % (e.value, e.document_order, e.source_url.split("/")[-1], e.candidate_count,
             tuple(e.boundary_issues), e.anchor_passed, e.keyword_passed, e.same_record, e.document_relation))
    print("     block=%s [%s:%s] snippet=%r" % (e.block_id, e.block_start, e.block_end, e.snippet[:160]))
