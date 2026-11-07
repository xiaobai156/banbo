from __future__ import annotations

import argparse
import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

from banbo.application import SinglePeriodRunner
from banbo.application.models import SiteRun
from banbo.domain import FailureCode, FailureResult, ValidatedResult
from banbo.parsers import build_default_registry, parse_parser_specs
from banbo.reporting import (
    ConsoleProgress,
    SuccessConflict,
    SuccessMerge,
    append_audit_jsonl,
    conflict_rejected_values,
    conflict_site_names,
    failure_site_names,
    merge_failure_report,
    merge_success_report,
    render_audit_jsonl,
    render_reconcile_jsonl,
    success_rows,
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
    parser.add_argument("--retry-failures", action="store_true", help="仅重抓当期失败TXT中的站点")
    parser.add_argument(
        "--accept-verified",
        action="store_true",
        help="解析器已修复并重新验证：用本次结果覆盖成功TXT与缓存里的不同旧值",
    )
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--no-update-cache", action="store_true")
    parser.add_argument("--shadow", action="store_true")
    parser.add_argument("--success-dir", type=Path, default=DEFAULT_SUCCESS_DIR)
    parser.add_argument("--failure-dir", type=Path, default=DEFAULT_FAILURE_DIR)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH)
    return parser


def _target_sites_from_failure_report(
    path: Path,
    period: int,
) -> tuple[list[str], list[str]]:
    """(可重试站点, 需人工裁决的冲突站点) from the official failure TXT."""

    if not path.exists():
        return [], []
    text = path.read_text(encoding="utf-8-sig")
    names = list(failure_site_names(text, period))
    conflicts = set(conflict_site_names(text, period))
    return (
        [name for name in names if name not in conflicts],
        [name for name in names if name in conflicts],
    )


def _cache_values_for_period(cache_path: Path, period: int) -> dict[str, str]:
    """Cache baseline for the period, used as a second conflict source."""

    if not cache_path.exists():
        return {}
    try:
        payload = RecentCacheRepository(cache_path).load()
    except Exception as exc:
        print(f"缓存无法读取，冲突检查只看成功TXT：{type(exc).__name__}: {exc}")
        return {}
    if int(period) not in {int(item) for item in payload.get("issues", [])}:
        return {}
    key = str(int(period))
    return {
        str(row["name"]): str(row["values"][key])
        for row in payload["sites"]
        if key in row.get("values", {})
    }


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
    accept_values: Mapping[str, str] | None = None,
    pending_alignment: bool = False,
) -> tuple[str, dict | None, str | None]:
    repository = RecentCacheRepository(cache_path)
    outcomes = [run.outcome for run in runs]
    names = {site.site_id: site.name for site in sites.all()}
    active_ids = [site.site_id for site in sites.all() if not site.archived]
    cache_site_rows_by_id = {
        site.site_id: {
            "name": site.name,
            "url": site.url,
            "pick": site.direction.value,
            "second_click": site.second_click,
        }
        for site in sites.all()
    }
    if not cache_path.exists():
        # 建基准会写一份 10 期窗口：子集跑会把“只验证了几个站”固化成基准，
        # 所以首次建基准必须全站跑，否则拒绝。
        if len(outcomes) != len(active_ids):
            raise ValueError(
                "缓存文件不存在：首次建基准必须跑全站"
                f"（当前只有 {len(outcomes)}/{len(active_ids)} 个站点结果）。"
                "要么全站跑一次建基准，要么加 --no-update-cache 只补 TXT/审计"
            )
        payload = {
            "schema": 1,
            "description": "杀半波重复检测最近10期基准数据；由每日指定期抓取自动覆盖更新。",
            "updated_at": None,
            "window_size": 10,
            "issues": list(range(period, period - 10, -1)),
            "partial_issues": [],
            "sites": [
                {
                    **row,
                    "values": {},
                    "failures": {},
                }
                for row in cache_site_rows_by_id.values()
            ],
            "parser_versions": {},
        }
        return (
            "按指定期数建立缓存基准",
            repository.prepare_existing_period(
                outcomes,
                site_names_by_id=names,
                target_issue=period,
                run_id=run_id,
                base_payload=payload,
                accept_values=accept_values,
            ),
            None,
        )
    if not outcomes:
        return "未补充定向缓存：本轮没有结果", None, None

    cache_snapshot = repository.load_snapshot()
    cache = copy.deepcopy(cache_snapshot.payload)
    # 不在此处改写缓存窗口。旧实现把 issues 直接换成「本次请求期往前 10 期」
    # 并过滤掉窗口外的 values/failures，导致补跑较早期数时静默删除较新期的
    # 历史值（例如补 297 会删掉 298 的全部值），且绕过了存储层「新期数必须
    # 走完整单期流程」的闸门。窗口推进与越界拒绝统一交给存储层判定。

    rows_by_name = {str(row["name"]): row for row in cache["sites"]}
    for outcome in outcomes:
        name = names.get(outcome.site_id)
        if name is None or name in rows_by_name:
            continue
        row = copy.deepcopy(cache_site_rows_by_id[outcome.site_id])
        row["values"] = {}
        row["failures"] = {}
        cache["sites"].append(row)
        rows_by_name[name] = row

    existing_issues = {int(issue) for issue in cache["issues"]}
    if period in existing_issues:
        # 窗口内已存在的期数：定向补写，不允许动窗口。
        return (
            "按指定期数建立缓存基准",
            repository.prepare_existing_period(
                outcomes,
                site_names_by_id=names,
                target_issue=period,
                run_id=run_id,
                base_payload=cache,
                accept_values=accept_values,
            ),
            cache_snapshot.digest,
        )
    if period > max(existing_issues) and len(outcomes) == len(active_ids):
        # 比缓存最新期更大的完整单期结果：推进窗口。
        return (
            "推进缓存窗口",
            repository.prepare_advance_complete_period(
                outcomes,
                site_names_by_id=names,
                target_issue=period,
                expected_site_count=len(active_ids),
                run_id=run_id,
                base_payload=cache,
                accept_values=accept_values,
            ),
            cache_snapshot.digest,
        )
    if pending_alignment:
        # 解析器修复后单站重跑一个窗口外的期数：TXT 改了，但缓存推进需要
        # 全站结果。这里不能静默——否则正式TXT 与缓存长期不一致。
        raise ValueError(
            f"窗口外期数（缓存窗口 {min(existing_issues)}-{max(existing_issues)}）"
            "无法自动对齐缓存：本窗口外期数的缓存必须由全站结果写入，"
            f"本轮只有 {len(outcomes)}/{len(active_ids)} 个站点；"
            "成功TXT 已更新但缓存未对齐，请全站重跑该期"
        )
    oldest_issue = min(existing_issues)
    newest_issue = max(existing_issues)
    if len(outcomes) == len(active_ids):
        # 全站跑了一个窗口外的旧期：缓存窗口不回溯，只更新正式输出。
        message = (
            f"旧期 {period} 在缓存窗口 {oldest_issue}-{newest_issue} 之外："
            "只写 TXT/审计，缓存窗口不回溯"
        )
        return message, None, None
    message = (
        f"期数 {period} 不在缓存窗口 {oldest_issue}-{newest_issue} 内且不是全站结果："
        "只写 TXT/审计，缓存未推进（窗口外的期数要进缓存必须全站跑）"
    )
    return message, None, None


def _apply_success_conflicts(
    runs: list[SiteRun],
    conflicts: tuple[SuccessConflict, ...],
    period: int,
) -> list[SiteRun]:
    """Turn "official TXT already holds a different value" into a failure.

    The new value is never written over the old one, and the site is reported
    through the failure TXT with its parse evidence kept, so the disagreement
    stays reviewable instead of silently flipping the official result.
    """

    if not conflicts:
        return list(runs)
    by_name = {item.site_name: item for item in conflicts}
    adjusted: list[SiteRun] = []
    for run in runs:
        conflict = by_name.get(run.site.name)
        if conflict is None:
            adjusted.append(run)
            continue
        evidence = (
            (run.outcome.evidence,)
            if isinstance(run.outcome, ValidatedResult)
            else ()
        )
        adjusted.append(
            replace(
                run,
                outcome=FailureResult(
                    site_id=run.site.site_id,
                    target_issue=period,
                    code=FailureCode.SAME_PERIOD_CONFLICT,
                    message=(
                        f"{conflict.source}已有不同结果，拒绝覆盖："
                        f"{conflict.site_name} "
                        f"{'/'.join(conflict.existing_values)}"
                        f" -> {conflict.new_value}"
                    ),
                    evidence=evidence,
                ),
            )
        )
    return adjusted


@dataclass(frozen=True)
class PeriodReportPlan:
    """What one run writes for one period, decided once for every entry point."""

    merge: SuccessMerge
    effective_runs: list[SiteRun]
    retained: dict[str, str]
    values_by_name: dict[str, str]


def _plan_period_reports(
    existing_success: str,
    period: int,
    runs: list[SiteRun],
    *,
    known_values: Mapping[str, str],
    accept_verified: bool = False,
    previous_conflicts: Mapping[str, str] | None = None,
) -> PeriodReportPlan:
    """Merge 成功TXT → turn conflicts into failures → keep final values visible.

    单期入口和多期入口都走这里，避免两个入口出现两套写入语义。
    """

    merge = merge_success_report(
        existing_success,
        period,
        runs,
        known_values=known_values,
        accept_verified=accept_verified,
    )
    effective_runs = _apply_success_conflicts(runs, merge.conflicts, period)
    values_by_name = {
        name: value for value, name in success_rows(merge.content, period)
    }
    conflict_names = {item.site_name for item in merge.conflicts}
    earlier = dict(previous_conflicts or {})
    retained: dict[str, str] = {}
    for run in effective_runs:
        if not isinstance(run.outcome, FailureResult):
            continue
        name = run.site.name
        value = values_by_name.get(name)
        if value is None or name in conflict_names:
            continue
        note = f"本次校验失败，已保留定稿值{value}"
        cached = known_values.get(name)
        if cached is not None and cached != value:
            note += f"；缓存值为{cached}，与定稿值不一致，需人工对齐"
        if name in earlier:
            # 上一轮冲突被拒绝的那个新值也要留下，否则这一行覆盖旧冲突行后
            # 就再也看不到“解析器当时给出的值是什么”。
            note += f"；上次拒绝的新值为{earlier[name]}"
        retained[name] = note
    return PeriodReportPlan(
        merge=merge,
        effective_runs=effective_runs,
        retained=retained,
        values_by_name=values_by_name,
    )


def _cache_accept_values(
    sites: SiteRepository,
    plan: PeriodReportPlan,
    known_values: Mapping[str, str],
) -> dict[str, str]:
    """Values the cache may adopt even though its own row differs.

    两件事：1) 成功TXT 与本次结果一致、缓存不同 → 缓存过期，按 TXT 对齐；
    2) 「保留」站点在缓存里缺这一期 → 把定稿值补回缓存。缓存已有不同值时
    不动它，留给人工对齐（失败TXT 里的「保留」记录会写明哪个值不一致）。
    """

    site_id_by_name = {site.name: site.site_id for site in sites.all()}
    accept: dict[str, str] = {}
    for name, value in plan.merge.cache_align.items():
        site_id = site_id_by_name.get(name)
        if site_id is not None:
            accept[site_id] = value
    for name in plan.retained:
        if name in known_values:
            continue
        value = plan.values_by_name.get(name)
        site_id = site_id_by_name.get(name)
        if value is not None and site_id is not None:
            accept[site_id] = value
    return accept


def _reconcile_entries(
    period: int,
    plan: PeriodReportPlan,
    known_values: Mapping[str, str],
    runs: list[SiteRun],
) -> list[dict[str, object]]:
    """Audit records for every value this run corrected in place.

    298 的教训是不能把“旧值是什么”抹掉：accept 覆盖和缓存对齐都要留下旧值、
    新值、run_id 和解析证据，否则事后无法复盘哪个值被谁改的。
    """

    runs_by_name = {
        run.site.name: run
        for run in runs
        if isinstance(run.outcome, ValidatedResult)
    }
    replaced = dict(plan.merge.replaced)
    aligned = dict(plan.merge.cache_align)
    accepted = set(plan.merge.accepted)
    entries: list[dict[str, object]] = []
    for name in sorted(set(replaced) | set(aligned) | accepted):
        run = runs_by_name.get(name)
        new_value = plan.values_by_name.get(name)
        if run is None or new_value is None:
            continue
        outcome = run.outcome
        evidence = outcome.evidence
        entries.append(
            {
                "period": int(period),
                "site_id": run.site.site_id,
                "site_name": name,
                "action": "accept_verified" if name in accepted else "cache_align",
                "old_txt_value": "/".join(replaced.get(name, ())) or None,
                "old_cache_value": known_values.get(name),
                "new_value": new_value,
                "parser_version": outcome.parser_version,
                "document_id": evidence.document_id,
                "block_id": evidence.block_id,
                "document_source": evidence.document_source.value,
                "source_url": evidence.source_url,
                "snippet": evidence.snippet,
                "anchors": list(evidence.anchors),
                "keywords": list(evidence.keywords),
                "boundary_issues": list(evidence.boundary_issues),
            }
        )
    return entries


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    period = _period_from_args(args.period)
    sites, specs, registry = _load_runtime()
    failure_path = args.failure_dir / f"{period}期-半波-失败.txt"
    if args.accept_verified and args.site_ids is None:
        # 覆盖已定稿的值必须是逐站决定，不接受一次全站自动覆盖。
        print(
            "--accept-verified 必须同时用 --site-id 指明要覆盖的站点，"
            "不支持全站自动覆盖"
        )
        return 2
    if args.retry_failures:
        retryable, conflicts = _target_sites_from_failure_report(
            failure_path, period
        )
        ids_by_name = {site.name: site.site_id for site in sites.all()}
        unknown = [
            name for name in (*retryable, *conflicts) if name not in ids_by_name
        ]
        if unknown:
            raise RuntimeConfigurationError("失败TXT存在未知站点：" + ",".join(unknown))
        if conflicts:
            # 冲突重试只会撞回同一个矛盾；显式点名该站并加 --accept-verified
            # 才能把新值写下去。
            print(
                "冲突记录需人工裁决，不自动重试："
                + ",".join(conflicts)
                + "（确认新值正确可加 --site-id 与 --accept-verified 重跑）"
            )
        allowed_names = (
            retryable + conflicts if args.site_ids is not None else retryable
        )
        failure_ids = [ids_by_name[name] for name in allowed_names]
        archived_ids = [
            site_id for site_id in failure_ids if sites.get(site_id).archived
        ]
        if archived_ids:
            print("已封存站点不再重试：" + ",".join(archived_ids))
            failure_ids = [
                site_id for site_id in failure_ids if site_id not in archived_ids
            ]
        if not failure_ids:
            print(f"未找到{period}期可重试的失败站点，已停止，未运行全站")
            # 只剩需人工裁决的冲突时不能报成功。
            return 1 if conflicts else 0
        if args.site_ids is None:
            args.site_ids = failure_ids
        else:
            selected = list(dict.fromkeys(args.site_ids))
            outside = [site_id for site_id in selected if site_id not in failure_ids]
            if outside:
                raise RuntimeConfigurationError("指定站点不在失败TXT中：" + ",".join(outside))
            args.site_ids = selected
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
    effective_runs: list[SiteRun] = list(runs)
    cache_failed = False
    if not args.shadow:
        success_path = args.success_dir / f"{period}期-半波.txt"
        failure_path = args.failure_dir / f"{period}期-半波-失败.txt"
        audit_path = BASE_DIR / "audit" / f"{period}.jsonl"
        previous_audit, audit_digest = read_text_snapshot(audit_path)
        operations: dict[Path, str | None] = {}
        expected_digests: dict[Path, str | None] = {}

        # 正式成功 TXT 按站点合并，不做整份覆盖：只跑部分站点（--site-id、
        # --retry-failures）时，其它站点的行必须原样保留；配置外的行同样
        # 保留。299 期就是整份重写把 195 站写成 3 行的。
        previous_success, success_digest = read_text_snapshot(success_path)
        previous_failure, failure_digest = read_text_snapshot(failure_path)
        known_values = _cache_values_for_period(args.cache, period)
        try:
            plan = _plan_period_reports(
                previous_success,
                period,
                runs,
                known_values=known_values,
                accept_verified=args.accept_verified,
                previous_conflicts=conflict_rejected_values(
                    previous_failure, period
                ),
            )
        except ValueError as exc:
            # 官方文件本身自相矛盾（同名不同值、期号不符）时停下来，
            # 不写半份结果，也不动缓存和审计。
            print(f"成功TXT无法安全合并，本轮未写入任何文件：{exc}")
            return 2
        merged_success = plan.merge.content
        effective_runs = plan.effective_runs
        if plan.merge.replaced:
            print(
                "已按 --accept-verified 覆盖成功TXT："
                + ",".join(
                    f"{name} {'/'.join(old)}->{plan.values_by_name.get(name, '')}"
                    for name, old in plan.merge.replaced.items()
                )
            )
        if plan.merge.conflicts:
            print(
                "已有不同结果，未覆盖，改记失败："
                + ",".join(
                    f"{item.site_name}({item.source})"
                    for item in plan.merge.conflicts
                )
                + "（确认新值正确可加 --accept-verified 重跑）"
            )
        if plan.merge.cache_align:
            print(
                "缓存与成功TXT不一致，已按TXT对齐："
                + ",".join(plan.merge.cache_align)
            )
        if merged_success != previous_success:
            operations[success_path] = merged_success
            expected_digests[success_path] = success_digest

        # 本期已有定稿值的站点这次失败：保留定稿值，改成「保留」记录——
        # 可见、可查，但不会被 --retry-failures 再抓一遍。
        if plan.retained:
            print(
                "以下站点本期已有定稿值，本次失败不改值，记「保留」："
                + ",".join(plan.retained)
            )

        # 失败 TXT 同样按站点合并：本次没碰到的站点，记录一条都不删。
        merged_failure = merge_failure_report(
            previous_failure,
            period,
            effective_runs,
            retained=plan.retained,
        )
        if merged_failure != previous_failure:
            operations[failure_path] = merged_failure or None
            expected_digests[failure_path] = failure_digest

        operations[audit_path] = append_audit_jsonl(
            previous_audit,
            render_audit_jsonl(effective_runs, run_id=run_id),
        )
        expected_digests[audit_path] = audit_digest

        # 被覆盖/对齐的旧值单独留档：这是唯一能证明“原来是什么”的地方。
        reconcile_path = BASE_DIR / "audit" / f"reconcile-{period}.jsonl"
        reconcile_entries = _reconcile_entries(
            period, plan, known_values, effective_runs
        )
        prepared_cache = None
        if args.no_update_cache:
            cache_message = "按参数跳过缓存"
        else:
            try:
                cache_message, updated_cache, cache_digest = _prepare_cache_update(
                    args.cache,
                    sites,
                    specs,
                    period,
                    effective_runs,
                    run_id=run_id,
                    accept_values=_cache_accept_values(
                        sites,
                        plan,
                        known_values,
                    ),
                    pending_alignment=bool(
                        plan.merge.accepted
                        or plan.merge.cache_align
                        or plan.retained
                    ),
                )
                if updated_cache is not None:
                    prepared_cache = (updated_cache, cache_digest)
            except Exception as exc:
                cache_failed = True
                cache_message = (
                    f"缓存更新失败：{type(exc).__name__}: {exc}"
                )
        if prepared_cache is not None:
            operations[args.cache] = render_json(prepared_cache[0])
            expected_digests[args.cache] = prepared_cache[1]
        if reconcile_entries:
            # 记录必须说明缓存到底有没有被对齐，否则看起来像已成功。
            cache_committed = (
                not args.no_update_cache
                and not cache_failed
                and prepared_cache is not None
            )
            for entry in reconcile_entries:
                entry["cache_committed"] = cache_committed
            previous_reconcile, reconcile_digest = read_text_snapshot(
                reconcile_path
            )
            operations[reconcile_path] = append_audit_jsonl(
                previous_reconcile,
                render_reconcile_jsonl(reconcile_entries, run_id=run_id),
            )
            expected_digests[reconcile_path] = reconcile_digest
        # 所有会落的角色路径统一查重：成功TXT/失败TXT/审计/缓存/修正日志
        # 任何一个被指到同一个文件，都会互相覆盖。
        written_paths = [success_path, failure_path, audit_path]
        if prepared_cache is not None:
            written_paths.append(args.cache)
        if reconcile_entries:
            written_paths.append(reconcile_path)
        resolved_paths = [path.resolve(strict=False) for path in written_paths]
        try:
            if len(resolved_paths) != len(set(resolved_paths)):
                raise ValueError("正式输出、审计和缓存路径不能重合")
            commit_files(operations, expected_digests=expected_digests)
        except Exception as exc:
            print(f"提交失败：{type(exc).__name__}: {exc}")
            return 2
    else:
        cache_message = "影子模式：未写入正式输出和缓存"
    successes = sum(run.succeeded for run in effective_runs)
    print(f"完成：成功 {successes}，失败 {len(effective_runs) - successes}")
    print(cache_message)
    if cache_failed:
        # 缓存没写进去就是“正式TXT 已更新、基准还是旧的”，不能报成功。
        print("缓存未更新，正式输出与缓存可能不一致，请处理后再视为完成")
        return 2
    return 0 if successes == len(effective_runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
