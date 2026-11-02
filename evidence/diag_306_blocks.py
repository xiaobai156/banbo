"""306 期可访问站点的取数层取证：定位每站自己区块里的 306 期有没有数值行。

只读诊断，不写配置/缓存/正式输出。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from banbo.application.single_period import build_site_spec  # noqa: E402
from banbo.fetch.document_discovery import (  # noqa: E402
    DiscoveryOptions,
    DocumentDiscoverer,
)
from banbo.fetch.http_client import HttpClient  # noqa: E402
from banbo.parsers.specs import parse_parser_specs  # noqa: E402
from banbo.parsers.text import html_to_text  # noqa: E402
from banbo.storage.site_repository import SiteRepository  # noqa: E402

TARGET = "306"
NAMES = ("片言一字", "好彩网", "人定胜天", "此曲已终")
OUT = ROOT / "evidence" / "diag_306_blocks.json"

sites = SiteRepository.from_json(ROOT / "config" / "sites.json")
specs = list(
    parse_parser_specs(
        json.loads((ROOT / "config" / "parser_specs.json").read_text(encoding="utf-8"))
    )
)
client = HttpClient(timeout=20, retries=2)
report: dict = {}

for name in NAMES:
    record = next(s for s in sites.all() if s.name == name)
    spec = next(s for s in specs if s.site_id == record.site_id)
    site = build_site_spec(record, spec)
    docs = DocumentDiscoverer(client).discover(
        site.url,
        options=DiscoveryOptions(
            allowed_external_hosts=tuple(spec.options.get("allowed_external_hosts", ())),
            script_path_markers=("/upload/script/", "/template/tags/", "/tags/"),
            render_browser=bool(spec.options.get("render_browser", False)),
        ),
        record_id_pattern=spec.record_id_pattern or spec.topic_id_pattern,
    )
    rows: list[dict] = []
    for doc in docs:
        text = html_to_text(doc.content or "")
        if name not in text and "半波" not in text:
            continue
        hits = [
            content
            for content in re.findall(
                r"[^\n]{0,60}" + TARGET + r"期[^\n]{0,80}", text
            )
        ]
        if not hits:
            continue
        rows.append(
            {
                "source": str(doc.source),
                "url": doc.source_url,
                "len": len(text),
                "has_name": name in text,
                "hits": hits[:6],
            }
        )
    report[name] = {"docs": len(docs), "rows": rows}
    print("=" * 20, name, "docs", len(docs), "命中文档", len(rows))
    for row in rows[:6]:
        print("  ", row["source"], row["url"], "len", row["len"], "含站名", row["has_name"])
        for hit in row["hits"]:
            print("     ", hit.strip()[:140])

OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
print("saved", OUT)
