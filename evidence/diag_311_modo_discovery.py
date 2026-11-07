# -*- coding: utf-8 -*-
"""只读：魔童（hw-0091）311 期“偶发 target_period_missing”取证。

连续执行文档发现 N 轮，记录每轮文档数量与文档来源集合，
再把失败轮与成功轮做差异，检查承载 311 区块的脚本文档是否缺失。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from banbo.application.single_period import build_site_spec  # noqa: E402
from banbo.fetch.document_discovery import DiscoveryOptions, DocumentDiscoverer  # noqa: E402
from banbo.fetch.http_client import HttpClient  # noqa: E402
from banbo.parsers.specs import parse_parser_specs  # noqa: E402
from banbo.parsers.text import html_to_text  # noqa: E402
from banbo.storage.site_repository import SiteRepository  # noqa: E402

SITE = "魔童"
PERIOD = "311"
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 6
OUT = ROOT / "evidence" / "diag_311_modo_discovery.json"

sites = SiteRepository.from_json(ROOT / "config" / "sites.json")
specs = list(
    parse_parser_specs(
        json.loads((ROOT / "config" / "parser_specs.json").read_text(encoding="utf-8"))
    )
)
record = next(s for s in sites.all() if s.name == SITE)
spec = next(s for s in specs if s.site_id == record.site_id)
site = build_site_spec(record, spec)
options = DiscoveryOptions(
    allowed_external_hosts=tuple(spec.options.get("allowed_external_hosts", ())),
    script_path_markers=("/upload/script/", "/template/tags/", "/tags/"),
    render_browser=bool(spec.options.get("render_browser", False)),
)

rounds = []
for round_index in range(ROUNDS):
    client = HttpClient(timeout=20, retries=2)
    docs = DocumentDiscoverer(client).discover(
        site.url,
        options=options,
        record_id_pattern=spec.record_id_pattern or spec.topic_id_pattern,
    )
    with_period = []
    for index, doc in enumerate(docs):
        text = html_to_text(doc.content or "")
        if "%s期" % PERIOD in text and "降世魔童" in text:
            with_period.append({"index": index, "id": doc.document_id,
                                "source": str(doc.source), "url": doc.source_url})
    rounds.append({
        "round": round_index + 1,
        "docs": len(docs),
        "ids": [doc.document_id for doc in docs],
        "period_docs": with_period,
    })
    print("round %d docs=%d 含311+降世魔童文档=%d %s" % (
        round_index + 1, len(docs), len(with_period),
        [d["source"] for d in with_period]))

good = [r for r in rounds if r["period_docs"]]
bad = [r for r in rounds if not r["period_docs"]]
print("\n成功轮 %d / 失败轮 %d" % (len(good), len(bad)))
if good and bad:
    good_set, bad_set = set(good[0]["ids"]), set(bad[0]["ids"])
    only_bad = sorted(bad_set - good_set)
    only_good = sorted(good_set - bad_set)
    print("仅失败轮有 %d 个文档：%s" % (len(only_bad), only_bad[:5]))
    print("仅成功轮有 %d 个文档：%s" % (len(only_good), only_good[:5]))
    counts = Counter(len(set(g["ids"])) for g in good)
    print("成功轮文档数分布", dict(counts))

OUT.write_text(json.dumps(rounds, ensure_ascii=False, indent=1), encoding="utf-8")
print("证据 ->", OUT)
