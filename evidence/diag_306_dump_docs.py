"""把指定站点的全部抓取层文档转储为文本文件，便于逐块核对（只读）。"""

from __future__ import annotations

import json
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

NAMES = sys.argv[1:] or ["片言一字"]
OUT_DIR = ROOT / "evidence" / "diag_306_doc_dumps"

sites = SiteRepository.from_json(ROOT / "config" / "sites.json")
specs = list(
    parse_parser_specs(
        json.loads((ROOT / "config" / "parser_specs.json").read_text(encoding="utf-8"))
    )
)
client = HttpClient(timeout=20, retries=2)
OUT_DIR.mkdir(exist_ok=True)

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
    lines = []
    for index, doc in enumerate(docs):
        text = html_to_text(doc.content or "")
        lines.append(
            json.dumps(
                {
                    "index": index,
                    "id": doc.document_id,
                    "source": str(doc.source),
                    "url": doc.source_url,
                    "len": len(text),
                },
                ensure_ascii=False,
            )
        )
        (OUT_DIR / f"{name}-{index:04d}.txt").write_text(text, encoding="utf-8")
    (OUT_DIR / f"{name}-index.jsonl").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(name, "docs", len(docs), "->", OUT_DIR)
