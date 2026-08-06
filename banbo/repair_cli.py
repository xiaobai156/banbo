from __future__ import annotations

import argparse
from pathlib import Path

from banbo.application import (
    SinglePeriodRunner,
    load_repair_cases,
    validate_repair_cases,
)
from banbo.cli import BASE_DIR, _load_runtime
from banbo.storage import atomic_write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="失败站点独立验证入口")
    parser.add_argument(
        "--cases",
        type=Path,
        default=BASE_DIR / "config" / "repair_cases.json",
    )
    args = parser.parse_args(argv)
    sites, specs, registry = _load_runtime()
    cases = load_repair_cases(args.cases, sites)
    runner = SinglePeriodRunner(sites, specs, registry)
    report = validate_repair_cases(cases, runner)
    output = BASE_DIR / "evidence" / "repair_validation_latest.json"
    atomic_write_json(
        output,
        {"schema_version": 1, "cases": report},
        backup=False,
    )
    for item in report:
        if item["passed"]:
            print(
                item["site_id"],
                "通过",
                item["issue"],
                item["value"],
                "候选数=" + str(item["candidate_count"]),
            )
        else:
            print(
                item["site_id"],
                "失败",
                item["issue"],
                item["failure_code"],
                item["failure_reason"],
            )
    return 0 if all(item["passed"] for item in report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
