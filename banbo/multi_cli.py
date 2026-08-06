from __future__ import annotations

import argparse
from pathlib import Path
from uuid import uuid4

from banbo.application import SinglePeriodRunner, run_periods
from banbo.cli import BASE_DIR, DEFAULT_FAILURE_DIR, DEFAULT_SUCCESS_DIR, _load_runtime
from banbo.reporting import (
    render_audit_jsonl,
    render_failure_report,
    render_multi_failure_report,
    render_success_report,
)
from banbo.storage import commit_files


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="杀半波解耦版多期入口")
    parser.add_argument("--periods", nargs="+", type=int)
    parser.add_argument("--site-id", action="append", dest="site_ids")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--success-dir", type=Path, default=DEFAULT_SUCCESS_DIR)
    parser.add_argument("--failure-dir", type=Path, default=DEFAULT_FAILURE_DIR)
    return parser


def _read_periods(values: list[int] | None) -> tuple[int, ...]:
    if values:
        entered = values
    else:
        raw = input("请输入多个期数，用空格隔开，例如187 188 189：").split()
        entered = [int(value) for value in raw]
    periods: list[int] = []
    for period in entered:
        if period <= 0:
            raise ValueError("期数必须是正整数")
        if period not in periods:
            periods.append(period)
    if not periods:
        raise ValueError("至少输入一个期数")
    return tuple(periods)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    periods = _read_periods(args.periods)
    sites, specs, registry = _load_runtime()
    runner = SinglePeriodRunner(sites, specs, registry)
    results = run_periods(
        runner,
        periods,
        site_ids=args.site_ids,
    )
    run_id = uuid4().hex
    runs_by_period: dict[int, list] = {period: [] for period in periods}
    for result in results:
        for run in result.periods:
            runs_by_period[run.outcome.target_issue].append(run)

    summary_path = (
        args.failure_dir
        / f"多期-{ '-'.join(str(period) for period in periods) }-半波-全部失败.txt"
    )
    operations: dict[Path, str | None] = {}
    for period in periods:
        runs = runs_by_period[period]
        operations[args.success_dir / f"{period}期-半波.txt"] = (
            render_success_report(period, runs)
        )
        failure_path = args.failure_dir / f"{period}期-半波-失败.txt"
        operations[failure_path] = render_failure_report(period, runs) or None
        operations[BASE_DIR / "audit" / f"multi-{run_id}-{period}.jsonl"] = (
            render_audit_jsonl(runs, run_id=run_id)
        )
    operations[summary_path] = render_multi_failure_report(results) or None
    try:
        commit_files(operations)
    except Exception as exc:
        print(f"多期输出提交失败：{type(exc).__name__}: {exc}")
        return 2
    passed = sum(result.passed for result in results)
    print(
        f"完成：站点通过 {passed}/{len(results)}；"
        f"多期任务不更新 recent_10_cache.json"
    )
    print(f"全部失败汇总：{summary_path}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
