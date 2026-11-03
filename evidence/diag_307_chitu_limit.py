# -*- coding: utf-8 -*-
"""只读：内存里抬高 hw-0109 的 max_response_bytes，验证 307 是否可解析（不写输出/缓存/审计）。

用法：py -3.10 evidence/diag_307_chitu_limit.py [site_id] [period] [limit_bytes]
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from banbo.application.single_period import SinglePeriodRunner  # noqa: E402
from banbo.domain import FailureResult, ValidatedResult  # noqa: E402
from banbo.parsers import build_default_registry, parse_parser_specs  # noqa: E402
from banbo.storage.site_repository import SiteRepository  # noqa: E402

SITE = sys.argv[1] if len(sys.argv) > 1 else "hw-0109"
PERIOD = int(sys.argv[2]) if len(sys.argv) > 2 else 307
LIMIT = int(sys.argv[3]) if len(sys.argv) > 3 else 32 * 1024 * 1024

sites = SiteRepository.from_json(ROOT / "config" / "sites.json")
specs = list(parse_parser_specs(json.loads((ROOT / "config" / "parser_specs.json").read_text(encoding="utf-8"))))
for i, s in enumerate(specs):
    if s.site_id == SITE:
        opts = dict(s.options)
        opts["max_response_bytes"] = LIMIT
        specs[i] = replace(s, options=opts)

registry = build_default_registry()
for s in specs:
    registry.bind(s)
runner = SinglePeriodRunner(sites, specs, registry)

run = runner.run_site(SITE, PERIOD)
outcome = run.outcome
print("limit=%d ok=%s docs=%s ms=%s" % (LIMIT, isinstance(outcome, ValidatedResult), run.document_count, run.elapsed_ms))
if isinstance(outcome, ValidatedResult):
    ev = outcome.evidence
    print("VALUE=%s direction=%s parser=%s v=%s" % (outcome.value, outcome.direction, ev.parser_id, outcome.parser_version))
    print("source=%s order=%s" % (ev.source_url, ev.document_order))
    print("block=%s [%s:%s] candidates=%s boundary=%s" % (ev.block_id, ev.block_start, ev.block_end, ev.candidate_count, tuple(ev.boundary_issues)))
    print("snippet=%r" % (ev.snippet[:200],))
else:
    print("CODE=%s msg=%s" % (outcome.code, outcome.message))
    for ev in getattr(outcome, "evidence", [])[:3]:
        print("  ev parser=%s block=%s source=%s cands=%s snippet=%r" % (ev.parser_id, ev.block_id, ev.source_url, ev.candidate_count, ev.snippet[:120]))
