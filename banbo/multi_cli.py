from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from banbo.application import SinglePeriodRunner, run_periods
from banbo.cli import (
    BASE_DIR,
    DEFAULT_CACHE_PATH,
    DEFAULT_FAILURE_DIR,
    DEFAULT_SUCCESS_DIR,
    _cache_values_for_period,
    _load_runtime,
    _plan_period_reports,
)
from banbo.reporting import (
    merge_failure_report,
    render_audit_jsonl,
    render_multi_failure_report,
)
from banbo.storage import commit_files, read_text_snapshot


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "杀半波解耦版多期入口（只验证：不写 recent_10_cache.json；"
            "缓存对齐与 --accept-verified 裁决请回单期入口）"
        )
    )
    parser.add_argument("--periods", nargs="+", type=int)
    parser.add_argument("--site-id", action="append", dest="site_ids")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--success-dir", type=Path, default=DEFAULT_SUCCESS_DIR)
    parser.add_argument("--failure-dir", type=Path, default=DEFAULT_FAILURE_DIR)
    parser.add_argument(
        "--cache",
        type=Path,
        default=DEFAULT_CACHE_PATH,
        help="只读缓存基准，用于和成功TXT 交叉判冲突（多期任务不写缓存）",
    )
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
        max_workers=args.max_workers,
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
    expected_digests: dict[Path, str | None] = {}
    retained_notes: dict[tuple[int, str], str] = {}
    for period in periods:
        runs = runs_by_period[period]
        success_path = args.success_dir / f"{period}期-半波.txt"
        failure_path = args.failure_dir / f"{period}期-半波-失败.txt"
        # 与单期入口同一套语义：合并、冲突改判、定稿值保留。
        previous_success, success_digest = read_text_snapshot(success_path)
        known_values = _cache_values_for_period(args.cache, period)
        try:
            plan = _plan_period_reports(
                previous_success,
                period,
                runs,
                known_values=known_values,
            )
        except ValueError as exc:
            print(f"{period} 成功TXT无法安全合并，本轮未写入任何文件：{exc}")
            return 2
        runs_by_period[period] = plan.effective_runs
        if plan.merge.conflicts:
            print(
                f"{period} 已有不同结果，未覆盖，改记失败："
                + ",".join(
                    f"{item.site_name}({item.source})"
                    for item in plan.merge.conflicts
                )
            )
        if plan.merge.cache_align:
            print(
                f"{period} 缓存与成功TXT不一致（多期不写缓存，留待单期对齐）："
                + ",".join(plan.merge.cache_align)
            )
        if plan.merge.content != previous_success:
            operations[success_path] = plan.merge.content
            expected_digests[success_path] = success_digest
        previous_failure, failure_digest = read_text_snapshot(failure_path)
        merged_failure = merge_failure_report(
            previous_failure,
            period,
            plan.effective_runs,
            retained=plan.retained,
        )
        if merged_failure != previous_failure:
            operations[failure_path] = merged_failure or None
            expected_digests[failure_path] = failure_digest
        for name, note in plan.retained.items():
            retained_notes[(int(period), name)] = note
        operations[BASE_DIR / "audit" / f"multi-{run_id}-{period}.jsonl"] = (
            render_audit_jsonl(plan.effective_runs, run_id=run_id)
        )
    # 汇总与退出码必须看冲突改判之后的 runs，否则冲突站在汇总里仍显示通过。
    effective_by_key = {
        (run.site.site_id, int(run.outcome.target_issue)): run
        for period in periods
        for run in runs_by_period[period]
    }
    effective_results = tuple(
        replace(
            result,
            periods=tuple(
                effective_by_key[
                    (result.site_id, int(run.outcome.target_issue))
                ]
                for run in result.periods
            ),
        )
        for result in results
    )
    operations[summary_path] = (
        render_multi_failure_report(
            effective_results,
            retained=retained_notes,
        )
        or None
    )
    try:
        commit_files(operations, expected_digests=expected_digests)
    except Exception as exc:
        print(f"多期输出提交失败：{type(exc).__name__}: {exc}")
        return 2
    passed = sum(result.passed for result in effective_results)
    period_runs = [
        run for result in effective_results for run in result.periods
    ]
    period_failures = sum(1 for run in period_runs if not run.succeeded)
    print(
        f"完成：站点任一期通过 {passed}/{len(effective_results)}；"
        f"期数结果 成功 {len(period_runs) - period_failures}，失败 {period_failures}；"
        f"多期任务不更新 recent_10_cache.json"
    )
    print(f"失败汇总：{summary_path}")
    # 退出码按期数结果算：部分期失败不能被「站点通过」掩盖。
    return 0 if not period_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
