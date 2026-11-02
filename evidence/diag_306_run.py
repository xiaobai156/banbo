"""只读诊断：对单个站点跑一次 SinglePeriodRunner.run_site（内存态，不写输出/缓存/审计），打印裁决细节。

用法：py -3.10 evidence/diag_306_run.py hw-0004 [period] [repeat]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from banbo.application.single_period import SinglePeriodRunner  # noqa: E402
from banbo.domain import FailureResult, ValidatedResult  # noqa: E402
from banbo.parsers import build_default_registry, parse_parser_specs  # noqa: E402
from banbo.storage.site_repository import SiteRepository  # noqa: E402


def describe(run) -> list[str]:
    lines = [
        f"ok={isinstance(run.outcome, ValidatedResult)} docs={run.document_count}"
        f" url={run.request_url} ms={run.elapsed_ms}"
    ]
    outcome = run.outcome
    if isinstance(outcome, ValidatedResult):
        ev = outcome.evidence
        lines.append(f"  VALUE={outcome.value} direction={outcome.direction}")
        lines.append(f"  parser={ev.parser_id} v={outcome.parser_version}")
        lines.append(f"  source={ev.source_url} order={ev.document_order} id={ev.document_id}")
        lines.append(f"  block={ev.block_id} [{ev.block_start}:{ev.block_end}]")
        lines.append(
            f"  candidates={ev.candidate_count} boundary={tuple(ev.boundary_issues)}"
            f" anchor={ev.anchor_passed} keyword={ev.keyword_passed} same_record={ev.same_record}"
            f" record_id={ev.record_id} expected={ev.expected_record_id}"
        )
        lines.append(f"  snippet={ev.snippet[:200]!r}")
    elif isinstance(outcome, FailureResult):
        lines.append(f"  CODE={outcome.code} msg={outcome.message}")
        for ev in outcome.evidence[:4]:
            lines.append(
                f"  ev parser={ev.parser_id} block={ev.block_id}"
                f" source={ev.source_url} order={ev.document_order}"
                f" cands={ev.candidate_count} boundary={tuple(ev.boundary_issues)}"
                f" value={ev.value!r} conflict={tuple(ev.conflict_values)}"
            )
            lines.append(f"    snippet={ev.snippet[:200]!r}")
    return lines


def main() -> int:
    site_id = sys.argv[1]
    period = int(sys.argv[2]) if len(sys.argv) > 2 else 306
    repeat = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    sites = SiteRepository.from_json(ROOT / "config" / "sites.json")
    specs = list(
        parse_parser_specs(
            json.loads((ROOT / "config" / "parser_specs.json").read_text(encoding="utf-8"))
        )
    )
    registry = build_default_registry()
    for spec in specs:
        registry.bind(spec)
    record = sites.get(site_id)
    runner = SinglePeriodRunner(sites, specs, registry)
    results = []
    for index in range(repeat):
        run = runner.run_site(site_id, period)
        results.append(isinstance(run.outcome, ValidatedResult))
        print(f"--- attempt {index + 1} ---")
        print("\n".join(describe(run)))
    print(f"\nSUMMARY site={site_id} name={record.name} period={period} ok={sum(results)}/{repeat}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
