from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from banbo.application import SinglePeriodRunner
from banbo.domain import ValidatedResult
from banbo.parsers import build_default_registry, parse_parser_specs
from banbo.reporting import (
    append_repair_successes,
    failure_site_names,
    remove_successful_failures,
    ConsoleProgress,
    append_audit_jsonl,
    render_audit_jsonl,
    render_failure_report,
    render_success_report,
)
from banbo.storage import (
    RecentCacheRepository,
    SiteRepository,
    commit_files,
    read_text_snapshot,
    render_json,
)


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SUCCESS_DIR = Path(
    r"C:\Users\Administrator\Desktop\每天工具\爬虫合集\七类数据统一归纳"
)
DEFAULT_FAILURE_DIR = Path(
    r"C:\Users\Administrator\Desktop\每天工具\爬虫合集\七类数据统一归纳失败"
)
DEFAULT_CACHE_PATH = BASE_DIR / "recent_10_cache.json"
SINGLE_SUCCESS_EXTRA_NAMES: tuple[str, ...] = ()


class RuntimeConfigurationError(ValueError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="杀半波解耦版严格入口")
    parser.add_argument("--period", type=int, help="指定单期，例如211")
    parser.add_argument("--site-id", action="append", dest="site_ids")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--no-update-cache", action="store_true")
    parser.add_argument("--shadow", action="store_true")
    parser.add_argument("--success-dir", type=Path, default=DEFAULT_SUCCESS_DIR)
    parser.add_argument("--failure-dir", type=Path, default=DEFAULT_FAILURE_DIR)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH)
    return parser


def _target_sites_from_failure_report(path: Path, period: int) -> list[str]:
    if not path.exists():
        return []
    return list(failure_site_names(path.read_text(encoding="utf-8-sig"), period))


def _validate_runtime_configuration(sites: SiteRepository, specs: list) -> None:
    site_ids = {site.site_id for site in sites.all()}
    spec_ids = {spec.site_id for spec in specs}
    missing_specs = sorted(site_ids - spec_ids)
    extra_specs = sorted(spec_ids - site_ids)
    if missing_specs or extra_specs:
        details: list[str] = []
        if missing_specs:
            details.append("缺少解析规格：" + ",".join(missing_specs))
        if extra_specs:
            details.append("存在未登记站点解析规格：" + ",".join(extra_specs))
        raise RuntimeConfigurationError("；".join(details))

    sites_by_id = {site.site_id: site for site in sites.all()}
    for spec in specs:
        site = sites_by_id[spec.site_id]
        if spec.direction != site.direction:
            raise RuntimeConfigurationError(
                f"站点与解析规格方向不一致：{spec.site_id}"
            )


def _load_runtime() -> tuple[SiteRepository, list, object]:
    sites = SiteRepository.from_json(BASE_DIR / "config" / "sites.json")
    specs = parse_parser_specs(
        json.loads(
            (BASE_DIR / "config" / "parser_specs.json").read_text(
                encoding="utf-8"
            )
        )
    )
    _validate_runtime_configuration(sites, list(specs))
    registry = build_default_registry()
    for spec in specs:
        registry.bind(spec)
    return sites, specs, registry


def _period_from_args(value: int | None) -> int:
    if value is not None:
        if value <= 0:
            raise ValueError("期数必须是正整数")
        return value
    entered = input("请输入期数，例如211：").strip()
    period = int(entered)
    if period <= 0:
        raise ValueError("期数必须是正整数")
    return period


def _prepare_cache_update(
    cache_path: Path,
    sites: SiteRepository,
    specs,
    period: int,
    runs,
    *,
    run_id: str,
) -> tuple[str, dict | None, str | None]:
    repository = RecentCacheRepository(cache_path)
    successful = [
        run.outcome for run in runs if isinstance(run.outcome, ValidatedResult)
    ]
    names = {site.site_id: site.name for site in sites.all()}
    cache_site_rows_by_id = {
        site.site_id: {
            "name": site.name,
            "url": site.url,
            "pick": site.direction.value,
            "second_click": site.second_click,
        }
        for site in sites.all()
    }
    site_count = len(sites.all())
    if len(runs) != site_count:
        if not successful:
            return "未补充定向缓存：本轮没有成功结果", None, None
        cache_snapshot = repository.load_snapshot()
        return (
            "补充定向站点缓存",
            repository.prepare_targeted_period(
                successful,
                site_names_by_id=names,
                target_issue=period,
                site_rows_by_id=cache_site_rows_by_id,
                run_id=run_id,
                base_payload=cache_snapshot.payload,
            ),
            cache_snapshot.digest,
        )
    cache_site_rows = list(cache_site_rows_by_id.values())
    cache_snapshot = repository.load_snapshot_for_sites(
        cache_site_rows,
        expected_parser_versions={
            spec.site_id: spec.parser_version for spec in specs
        },
    )
    cache = cache_snapshot.payload
    if period in {int(issue) for issue in cache["issues"]}:
        if not successful:
            return "未补充缓存：本轮没有成功结果", None, None
        return (
            "补充已有缓存期",
            repository.prepare_existing_period(
                successful,
                site_names_by_id=names,
                target_issue=period,
                run_id=run_id,
                base_payload=cache,
                expected_site_count=len(sites.all()),
                expected_site_names=names.values(),
            ),
            cache_snapshot.digest,
        )
    success_count = len(successful)
    success_rate = success_count * 100 / site_count
    if success_count * 100 <= site_count * 85:
        return (
            "未推进缓存："
            f"成功率{success_rate:.2f}%未超过85%"
            f"（{success_count}/{site_count}）",
            None,
            None,
        )
    return (
        f"推进缓存新期：成功率{success_rate:.2f}%"
        f"（{success_count}/{site_count}）",
        repository.prepare_advance_complete_period(
            [run.outcome for run in runs],
            site_names_by_id=names,
            target_issue=period,
            expected_site_count=site_count,
            run_id=run_id,
            base_payload=cache,
            expected_site_names=names.values(),
        ),
        cache_snapshot.digest,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    period = _period_from_args(args.period)
    sites, specs, registry = _load_runtime()
    failure_path = args.failure_dir / f"{period}期-半波-失败.txt"
    if args.site_ids is None:
        names = _target_sites_from_failure_report(failure_path, period)
        ids_by_name = {site.name: site.site_id for site in sites.all()}
        unknown = [name for name in names if name not in ids_by_name]
        if unknown:
            raise RuntimeConfigurationError("失败TXT存在未知站点：" + ",".join(unknown))
        args.site_ids = [ids_by_name[name] for name in names]
        if not args.site_ids:
            print(f"未找到{period}期失败站点，已停止，未运行全站")
            return 0
    runner = SinglePeriodRunner(sites, specs, registry)
    progress = ConsoleProgress()
    try:
        runs = runner.run_many(
            period,
            site_ids=args.site_ids,
            max_workers=args.max_workers,
            progress_callback=progress,
        )
    finally:
        progress.finish()
    run_id = uuid4().hex
    if not args.shadow:
        success_path = args.success_dir / f"{period}期-半波.txt"
        audit_path = BASE_DIR / "audit" / f"{period}.jsonl"
        previous_audit, audit_digest = read_text_snapshot(audit_path)
        operations: dict[Path, str | None] = {
            audit_path: append_audit_jsonl(
                previous_audit,
                render_audit_jsonl(runs, run_id=run_id),
            ),
        }
        expected_digests = {audit_path: audit_digest}
        if args.site_ids is not None:
            previous_success, success_digest = read_text_snapshot(success_path)
            updated_success = append_repair_successes(previous_success, runs)
            if updated_success != previous_success:
                operations[success_path] = updated_success
                expected_digests[success_path] = success_digest
            previous_failure, failure_digest = read_text_snapshot(failure_path)
            successful_names = {
                run.site.name for run in runs
                if isinstance(run.outcome, ValidatedResult)
            }
            updated_failure = remove_successful_failures(
                previous_failure, period, successful_names
            )
            if updated_failure != previous_failure:
                operations[failure_path] = updated_failure or None
                expected_digests[failure_path] = failure_digest
        else:
            operations[success_path] = render_success_report(
                period,
                runs,
                extra_names=SINGLE_SUCCESS_EXTRA_NAMES,
            )
            operations[failure_path] = render_failure_report(period, runs) or None
        operation_paths = [
            path.resolve(strict=False) for path in operations
        ]
        if not args.no_update_cache:
            operation_paths.append(args.cache.resolve(strict=False))
        try:
            if len(operation_paths) != len(set(operation_paths)):
                raise ValueError("正式输出、审计和缓存路径不能重合")
            commit_files(
                operations,
                expected_digests=expected_digests,
            )
        except Exception as exc:
            print(f"提交失败：{type(exc).__name__}: {exc}")
            return 2

        if args.no_update_cache:
            cache_message = "按参数跳过缓存"
        else:
            try:
                cache_message, updated_cache, cache_digest = _prepare_cache_update(
                    args.cache,
                    sites,
                    specs,
                    period,
                    runs,
                    run_id=run_id,
                )
                if updated_cache is not None:
                    expected_digests = (
                        {args.cache: cache_digest}
                        if cache_digest is not None
                        else None
                    )
                    commit_files(
                        {args.cache: render_json(updated_cache)},
                        backup_paths={args.cache},
                        expected_digests=expected_digests,
                    )
            except Exception as exc:
                cache_message = (
                    f"缓存更新未完成：{type(exc).__name__}: {exc}"
                )
    else:
        cache_message = "影子模式：未写入正式输出和缓存"
    successes = sum(run.succeeded for run in runs)
    print(f"完成：成功 {successes}，失败 {len(runs) - successes}")
    print(cache_message)
    return 0 if successes == len(runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
