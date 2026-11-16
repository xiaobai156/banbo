# -*- coding: utf-8 -*-
"""只读：hw-0052 按脚本分组，检查 320 半波行所在组是否含锚点。"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from banbo.application.single_period import build_site_spec  # noqa: E402
from banbo.fetch.document_discovery import DiscoveryOptions, DocumentDiscoverer  # noqa: E402
from banbo.fetch.http_client import HttpClient  # noqa: E402
from banbo.parsers.specs import parse_parser_specs  # noqa: E402
from banbo.storage.site_repository import SiteRepository  # noqa: E402

site_id = sys.argv[1]
period = sys.argv[2]
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
print("docs", len(docs), "anchors", spec.anchors, "keywords", spec.keywords)

def parent(src):
    return re.sub(r"#decoded-\d+$", "", src, flags=re.I)

groups = defaultdict(list)
for d in docs:
    groups[parent(d.source_url)].append(d)

hit_re = re.compile(r"%s\s*期[^期]{0,60}?[红绿蓝](?:波)?[单双]" % period)
for f, items in groups.items():
    texts = {id(d): (d.content or "") for d in items}
    combined = " ".join(re.sub(r"<[^>]+>", " ", t) for t in texts.values())
    has_anchor = any(a in combined for a in spec.anchors)
    has_half = "半波" in combined
    m = hit_re.search(combined)
    if not (has_half or m):
        continue
    print("\nFILE", f, "docs=%d anchor=%s halfwave=%s hit=%s" % (len(items), has_anchor, has_half, bool(m)))
    if m:
        print("   hit:", m.group(0)[:120])
    for d in sorted(items, key=lambda x: x.order)[:6]:
        t = re.sub(r"<[^>]+>", " ", d.content or "")
        t = re.sub(r"\s+", " ", t).strip()
        print("   [%d] %s :: %s" % (d.order, d.source_url.split("#")[-1], t[:140]))
