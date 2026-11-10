# -*- coding: utf-8 -*-
"""只读：导出指定站中同时含 needle 与指定期号的文档正文（含期号列表）。
用法：py -3.10 evidence/diag_313_blocks.py <site_id> <needle> [period] [max_docs]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from banbo.application.single_period import build_site_spec  # noqa: E402
from banbo.fetch.document_discovery import DiscoveryOptions, DocumentDiscoverer  # noqa: E402
from banbo.fetch.http_client import HttpClient  # noqa: E402
from banbo.parsers.specs import parse_parser_specs  # noqa: E402
from banbo.storage.site_repository import SiteRepository  # noqa: E402


def main() -> int:
    site_id = sys.argv[1]
    needle = sys.argv[2]
    period = sys.argv[3] if len(sys.argv) > 3 else ""
    max_docs = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    sites = SiteRepository.from_json(ROOT / "config" / "sites.json")
    specs = list(
        parse_parser_specs(
            json.loads((ROOT / "config" / "parser_specs.json").read_text(encoding="utf-8"))
        )
    )
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
    print("docs", len(docs), "needle", needle, "period", period)
    issue_re = re.compile(r"(\d{1,4})\s*期")
    shown = 0
    for index, doc in enumerate(docs):
        raw = doc.content or ""
        if needle not in raw:
            continue
        if period and period not in raw:
            continue
        shown += 1
        if shown > max_docs:
            break
        print("\n#### doc[%d] %s len=%d" % (index, doc.source_url, len(raw)))
        print("issues:", issue_re.findall(raw)[:25])
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
        print(text[:2000])
    print("\nTOTAL docs matching:", shown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
