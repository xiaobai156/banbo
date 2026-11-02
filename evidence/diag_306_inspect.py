"""只读诊断：重建指定站点的抓取层文档集，全文导出命中子串的文档及其相邻文档。

用法：py -3.10 evidence/diag_306_inspect.py hw-0004 306期 2
只写 evidence/diag_306_inspect_<site>.txt，不改配置/缓存/输出。
"""
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


def main() -> int:
    site_id = sys.argv[1]
    needle = sys.argv[2] if len(sys.argv) > 2 else "306期"
    context = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    sites = SiteRepository.from_json(ROOT / "config" / "sites.json")
    specs = list(
        parse_parser_specs(
            json.loads((ROOT / "config" / "parser_specs.json").read_text(encoding="utf-8"))
        )
    )
    record = next(s for s in sites.all() if s.site_id == site_id)
    spec = next(s for s in specs if s.site_id == site_id)
    site = build_site_spec(record, spec)
    client = HttpClient(timeout=20, retries=2)
    try:
        docs = DocumentDiscoverer(client).discover(
            site.url,
            options=DiscoveryOptions(
                allowed_external_hosts=tuple(spec.options.get("allowed_external_hosts", ())),
                script_path_markers=("/upload/script/", "/template/tags/", "/tags/"),
                render_browser=bool(spec.options.get("render_browser", False)),
            ),
            record_id_pattern=spec.record_id_pattern or spec.topic_id_pattern,
        )
    finally:
        client.close()

    texts = [html_to_text(d.content or "") for d in docs]
    hits = [i for i, t in enumerate(texts) if needle in t]
    out = [f"# {site_id} {record.name} docs={len(docs)} hits={len(hits)} needle={needle}"]
    seen: set[int] = set()
    for i in hits:
        for j in range(max(0, i - context), min(len(docs), i + context + 1)):
            if j in seen:
                continue
            seen.add(j)
            text = texts[j]
            anchor = any(a in text for a in spec.anchors)
            out.append(
                f"\n[{j}] source={docs[j].source} url={docs[j].source_url}"
                f" len={len(text)} anchor={anchor}"
                f"\n{text}"
            )
    path = ROOT / "evidence" / f"diag_306_inspect_{site_id}.txt"
    path.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\nsaved {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
