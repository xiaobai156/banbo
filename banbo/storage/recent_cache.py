from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
from uuid import uuid4

from banbo.domain.models import FailureResult, ValidatedResult
from banbo.domain.normalization import normalize_half_wave


class CacheValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CacheSnapshot:
    payload: dict
    digest: str


class RecentCacheRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(
        self,
        *,
        expected_site_count: int | None = None,
        expected_site_names: Iterable[str] | None = None,
    ) -> dict:
        return self.load_snapshot(
            expected_site_count=expected_site_count,
            expected_site_names=expected_site_names,
        ).payload

    def load_snapshot(
        self,
        *,
        expected_site_count: int | None = None,
        expected_site_names: Iterable[str] | None = None,
    ) -> CacheSnapshot:
        expected_names = (
            None
            if expected_site_names is None
            else tuple(str(name) for name in expected_site_names)
        )
        raw = self.path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
        self.validate(
            payload,
            expected_site_count=expected_site_count,
            expected_site_names=expected_names,
        )
        digest = hashlib.sha256(raw).hexdigest()
        return CacheSnapshot(payload=payload, digest=digest)

    def load_snapshot_for_sites(
        self,
        site_rows: Iterable[Mapping[str, object]],
        *,
        expected_parser_versions: Mapping[str, object] | None = None,
    ) -> CacheSnapshot:
        """Load cache and add empty rows for newly configured sites.

        Missing historical rows are not failures and must not prevent the
        current period from being evaluated. The original file digest is
        retained so a later atomic write still detects concurrent changes.
        """

        defaults = tuple(copy.deepcopy(dict(row)) for row in site_rows)
        if not defaults:
            raise CacheValidationError("正式站点集合为空")
        names = tuple(str(row.get("name", "")) for row in defaults)
        if any(not name for name in names) or len(names) != len(set(names)):
            raise CacheValidationError("正式站点名称为空或重复")
        snapshot = self.load_snapshot()
        normalized = self.prepare_site_rows(
            snapshot.payload,
            defaults,
        )
        self.validate(
            normalized,
            expected_site_count=len(names),
            expected_site_names=names,
            expected_parser_versions=expected_parser_versions,
        )
        return CacheSnapshot(payload=normalized, digest=snapshot.digest)

    @staticmethod
    def prepare_site_rows(
        payload: Mapping[str, object],
        site_rows: Iterable[Mapping[str, object]],
    ) -> dict:
        """Return a cache payload aligned to the current formal site set."""

        defaults = tuple(copy.deepcopy(dict(row)) for row in site_rows)
        if not defaults:
            raise CacheValidationError("正式站点集合为空")
        expected_names = tuple(str(row.get("name", "")) for row in defaults)
        if any(not name for name in expected_names):
            raise CacheValidationError("正式站点名称为空")
        if len(expected_names) != len(set(expected_names)):
            raise CacheValidationError("正式站点名称重复")

        RecentCacheRepository.validate(payload)
        existing_rows = payload["sites"]
        existing_by_name = {
            str(row["name"]): row
            for row in existing_rows
        }
        unexpected = sorted(set(existing_by_name) - set(expected_names))
        if unexpected:
            raise CacheValidationError(
                "缓存包含非正式站点：" + ",".join(unexpected)
            )

        updated = copy.deepcopy(dict(payload))
        normalized_rows: list[dict] = []
        for default in defaults:
            name = str(default["name"])
            existing = existing_by_name.get(name)
            if existing is None:
                row = default
                row["values"] = {}
                row["failures"] = {}
            else:
                for key in ("url", "pick", "second_click"):
                    if existing.get(key) != default.get(key):
                        raise CacheValidationError(
                            f"缓存站点身份与正式配置不一致：{name}.{key}"
                        )
                row = copy.deepcopy(dict(existing))
                row.setdefault("failures", {})
            normalized_rows.append(row)
        updated["sites"] = normalized_rows
        return updated

    @staticmethod
    def validate(
        payload: Mapping[str, object],
        *,
        expected_site_count: int | None = None,
        expected_site_names: Iterable[str] | None = None,
        expected_parser_versions: Mapping[str, object] | None = None,
    ) -> None:
        if not isinstance(payload, Mapping):
            raise CacheValidationError("缓存根节点不是对象")
        issues = payload.get("issues")
        sites = payload.get("sites")
        window_size = payload.get("window_size")
        if not isinstance(issues, list) or not issues:
            raise CacheValidationError("缓存期数窗口为空")
        if (
            not isinstance(window_size, int)
            or isinstance(window_size, bool)
            or window_size != len(issues)
        ):
            raise CacheValidationError("缓存窗口大小与期数数量不一致")
        if any(
            isinstance(issue, bool) or not isinstance(issue, (int, str))
            for issue in issues
        ):
            raise CacheValidationError("缓存期数格式无效")
        try:
            issue_sequence = [int(issue) for issue in issues]
        except (TypeError, ValueError) as exc:
            raise CacheValidationError("缓存期数格式无效") from exc
        if any(issue <= 0 for issue in issue_sequence):
            raise CacheValidationError("缓存期数必须是正整数")
        if len(set(issue_sequence)) != len(issues):
            raise CacheValidationError("缓存期数重复")
        if any(
            newer <= older
            for newer, older in zip(issue_sequence, issue_sequence[1:])
        ):
            raise CacheValidationError("缓存期数必须按从新到旧严格降序排列")
        issue_numbers = set(issue_sequence)
        partial_issues = payload.get("partial_issues", [])
        if not isinstance(partial_issues, list):
            raise CacheValidationError("定向缓存期数字段无效")
        try:
            partial_issue_sequence = [int(issue) for issue in partial_issues]
        except (TypeError, ValueError) as exc:
            raise CacheValidationError("定向缓存期数格式无效") from exc
        if (
            any(issue <= 0 for issue in partial_issue_sequence)
            or len(set(partial_issue_sequence)) != len(partial_issue_sequence)
            or issue_numbers.intersection(partial_issue_sequence)
        ):
            raise CacheValidationError("定向缓存期数无效或与全站窗口重复")
        if any(
            newer <= older
            for newer, older in zip(
                partial_issue_sequence, partial_issue_sequence[1:]
            )
        ):
            raise CacheValidationError("定向缓存期数必须按从新到旧严格降序排列")
        allowed_issue_numbers = issue_numbers | set(partial_issue_sequence)
        if not isinstance(sites, list) or not sites:
            raise CacheValidationError("缓存站点列表为空")
        if expected_site_count is not None and len(sites) != expected_site_count:
            raise CacheValidationError("缓存站点数量不完整")
        names: set[str] = set()
        for site in sites:
            if not isinstance(site, Mapping):
                raise CacheValidationError("缓存站点记录无效")
            name = str(site.get("name", ""))
            if not name or name in names:
                raise CacheValidationError("缓存站点名称为空或重复")
            names.add(name)
            values = site.get("values")
            if not isinstance(values, Mapping):
                raise CacheValidationError(f"缓存值字段无效：{name}")
            for issue, value in values.items():
                try:
                    issue_number = int(issue)
                except (TypeError, ValueError) as exc:
                    raise CacheValidationError(
                        f"缓存期数字段无效：{name}"
                    ) from exc
                if issue_number not in allowed_issue_numbers:
                    raise CacheValidationError(f"缓存存在窗口外期数：{name}")
                if normalize_half_wave(str(value)) is None:
                    raise CacheValidationError(f"缓存半波值无效：{name}")
            failures = site.get("failures", {})
            if not isinstance(failures, Mapping):
                raise CacheValidationError(f"缓存失败字段无效：{name}")
            value_issues = {int(issue) for issue in values}
            for issue, failure in failures.items():
                try:
                    issue_number = int(issue)
                except (TypeError, ValueError) as exc:
                    raise CacheValidationError(
                        f"缓存失败期数字段无效：{name}"
                    ) from exc
                if issue_number not in allowed_issue_numbers:
                    raise CacheValidationError(
                        f"缓存失败记录存在窗口外期数：{name}"
                    )
                if issue_number in value_issues:
                    raise CacheValidationError(
                        f"缓存同一期同时成功和失败：{name}"
                    )
                if not isinstance(failure, Mapping):
                    raise CacheValidationError(f"缓存失败记录无效：{name}")
                code = failure.get("code")
                reason = failure.get("reason")
                if (
                    not isinstance(code, str)
                    or not code.strip()
                    or not isinstance(reason, str)
                    or not reason.strip()
                ):
                    raise CacheValidationError(
                        f"缓存失败代码或原因无效：{name}"
                    )
        parser_versions = payload.get("parser_versions")
        if parser_versions is not None and not isinstance(parser_versions, Mapping):
            raise CacheValidationError("缓存解析版本字段无效")
        if expected_parser_versions is not None:
            expected_versions = {
                str(site_id): str(version)
                for site_id, version in expected_parser_versions.items()
            }
            actual_versions = {
                str(site_id): str(version)
                for site_id, version in (parser_versions or {}).items()
            }
            unknown_versions = sorted(set(actual_versions) - set(expected_versions))
            if unknown_versions:
                raise CacheValidationError(
                    "缓存包含未知解析版本：" + ",".join(unknown_versions)
                )
            mismatched_versions = sorted(
                site_id
                for site_id, version in actual_versions.items()
                if version != expected_versions[site_id]
            )
            if mismatched_versions:
                raise CacheValidationError(
                    "缓存解析版本与正式配置不一致："
                    + ",".join(mismatched_versions)
                )
        if expected_site_names is not None:
            expected_names = {str(name) for name in expected_site_names}
            if names != expected_names:
                raise CacheValidationError("缓存站点集合与正式站点不一致")

    def prepare_existing_period(
        self,
        results: Iterable[ValidatedResult],
        *,
        site_names_by_id: Mapping[str, str],
        target_issue: int,
        run_id: str | None = None,
        base_payload: Mapping[str, object] | None = None,
        expected_site_count: int | None = None,
        expected_site_names: Iterable[str] | None = None,
    ) -> dict:
        expected_names = (
            None
            if expected_site_names is None
            else tuple(str(name) for name in expected_site_names)
        )
        if base_payload is None:
            payload = self.load(
                expected_site_count=expected_site_count,
                expected_site_names=expected_names,
            )
        else:
            self.validate(
                base_payload,
                expected_site_count=expected_site_count,
                expected_site_names=expected_names,
            )
            payload = dict(base_payload)
        issue_key = str(int(target_issue))
        if int(target_issue) not in {int(item) for item in payload["issues"]}:
            raise CacheValidationError("新期数必须走完整单期流程，不能局部补写")
        updated = copy.deepcopy(payload)
        rows_by_name = {str(row["name"]): row for row in updated["sites"]}
        seen: set[str] = set()
        raw_parser_versions = updated.get("parser_versions", {})
        if not isinstance(raw_parser_versions, Mapping):
            raise CacheValidationError("缓存解析版本字段无效")
        parser_versions = {
            str(site_id): str(version)
            for site_id, version in raw_parser_versions.items()
        }
        for result in results:
            if not isinstance(result, ValidatedResult):
                raise CacheValidationError("缓存只能接收ValidatedResult")
            if result.target_issue != target_issue:
                raise CacheValidationError("结果期数与缓存目标期不一致")
            name = site_names_by_id.get(result.site_id)
            if name is None or name in seen or name not in rows_by_name:
                raise CacheValidationError("结果站点不在正式缓存中或重复")
            seen.add(name)
            rows_by_name[name]["values"][issue_key] = result.value
            failures = rows_by_name[name].get("failures")
            if isinstance(failures, dict):
                failures.pop(issue_key, None)
            parser_versions[result.site_id] = result.parser_version
        if not seen:
            raise CacheValidationError("没有可写入的成功结果")
        updated["updated_at"] = datetime.now(timezone.utc).isoformat()
        updated["last_run_id"] = run_id or uuid4().hex
        updated["parser_versions"] = parser_versions
        self.validate(
            updated,
            expected_site_count=expected_site_count,
            expected_site_names=expected_names,
        )
        return updated

    def prepare_targeted_period(
        self,
        results: Iterable[ValidatedResult],
        *,
        site_names_by_id: Mapping[str, str],
        target_issue: int,
        site_rows_by_id: Mapping[str, Mapping[str, object]] | None = None,
        run_id: str | None = None,
        base_payload: Mapping[str, object] | None = None,
    ) -> dict:
        payload = self.load() if base_payload is None else dict(base_payload)
        self.validate(payload)
        updated = copy.deepcopy(payload)
        rows_by_name = {str(row["name"]): row for row in updated["sites"]}
        parser_versions = {
            str(site_id): str(version)
            for site_id, version in updated.get("parser_versions", {}).items()
        }
        issue_key = str(int(target_issue))
        seen: set[str] = set()
        for result in results:
            if not isinstance(result, ValidatedResult):
                raise CacheValidationError("定向缓存只能接收ValidatedResult")
            if result.target_issue != target_issue:
                raise CacheValidationError("结果期数与定向缓存目标期不一致")
            name = site_names_by_id.get(result.site_id)
            row = rows_by_name.get(str(name))
            if name is None or row is None or name in seen:
                raise CacheValidationError("定向结果站点不在正式缓存中或重复")
            expected = (site_rows_by_id or {}).get(result.site_id)
            if expected is not None and any(
                row.get(key) != expected.get(key)
                for key in ("url", "pick", "second_click")
            ):
                raise CacheValidationError(f"缓存站点身份与正式配置不一致：{name}")
            seen.add(name)
            row["values"][issue_key] = result.value
            failures = row.setdefault("failures", {})
            if not isinstance(failures, dict):
                raise CacheValidationError(f"缓存失败字段无效：{name}")
            failures.pop(issue_key, None)
            parser_versions[result.site_id] = result.parser_version
        if not seen:
            raise CacheValidationError("没有可写入的定向成功结果")
        if int(target_issue) not in {int(issue) for issue in updated["issues"]}:
            partial = {
                int(issue) for issue in updated.get("partial_issues", [])
            }
            partial.add(int(target_issue))
            updated["partial_issues"] = sorted(partial, reverse=True)
        updated["updated_at"] = datetime.now(timezone.utc).isoformat()
        updated["last_run_id"] = run_id or uuid4().hex
        updated["parser_versions"] = parser_versions
        self.validate(updated)
        return updated

    def prepare_advance_complete_period(
        self,
        results: Iterable[ValidatedResult | FailureResult],
        *,
        site_names_by_id: Mapping[str, str],
        target_issue: int,
        expected_site_count: int,
        run_id: str | None = None,
        base_payload: Mapping[str, object] | None = None,
        expected_site_names: Iterable[str] | None = None,
    ) -> dict:
        expected_names = (
            None
            if expected_site_names is None
            else tuple(str(name) for name in expected_site_names)
        )
        if base_payload is None:
            payload = self.load(
                expected_site_count=expected_site_count,
                expected_site_names=expected_names,
            )
        else:
            self.validate(
                base_payload,
                expected_site_count=expected_site_count,
                expected_site_names=expected_names,
            )
            payload = dict(base_payload)
        if int(target_issue) in {int(item) for item in payload["issues"]}:
            raise CacheValidationError("已存在的期数不能重复推进窗口")
        if int(target_issue) <= max(int(item) for item in payload["issues"]):
            raise CacheValidationError("只能推进比当前缓存最新期更大的期数")
        result_list = list(results)
        if len(result_list) != expected_site_count:
            raise CacheValidationError("新期数必须包含全部正式站点结果")
        success_count = sum(
            isinstance(result, ValidatedResult) for result in result_list
        )
        if success_count * 100 <= expected_site_count * 85:
            raise CacheValidationError("新期数成功率必须严格超过85%")
        updated = copy.deepcopy(payload)
        rows_by_name = {str(row["name"]): row for row in updated["sites"]}
        if len(rows_by_name) != expected_site_count:
            raise CacheValidationError("正式缓存站点数量不完整")
        target_key = str(int(target_issue))
        raw_parser_versions = updated.get("parser_versions", {})
        if not isinstance(raw_parser_versions, Mapping):
            raise CacheValidationError("缓存解析版本字段无效")
        parser_versions = {
            str(site_id): str(version)
            for site_id, version in raw_parser_versions.items()
        }
        seen: set[str] = set()
        for result in result_list:
            if not isinstance(result, (ValidatedResult, FailureResult)):
                raise CacheValidationError("缓存只能接收正式校验结果")
            if result.target_issue != target_issue:
                raise CacheValidationError("结果期数与新缓存期数不一致")
            name = site_names_by_id.get(result.site_id)
            if name is None or name in seen or name not in rows_by_name:
                raise CacheValidationError("结果站点集合不完整或重复")
            seen.add(name)
            row = rows_by_name[name]
            failures = row.setdefault("failures", {})
            if not isinstance(failures, dict):
                raise CacheValidationError(f"缓存失败字段无效：{name}")
            if isinstance(result, ValidatedResult):
                row["values"][target_key] = result.value
                failures.pop(target_key, None)
                parser_versions[result.site_id] = result.parser_version
            else:
                row["values"].pop(target_key, None)
                failures[target_key] = {
                    "code": result.code.value,
                    "reason": result.message,
                }
        if len(seen) != expected_site_count:
            raise CacheValidationError("结果站点集合不完整")
        window_size = int(updated["window_size"])
        updated["issues"] = [int(target_issue)] + [
            int(issue) for issue in updated["issues"][: max(0, window_size - 1)]
        ]
        partial_issues = [
            int(issue)
            for issue in updated.get("partial_issues", [])
            if int(issue) not in updated["issues"]
        ]
        if partial_issues:
            updated["partial_issues"] = partial_issues
        else:
            updated.pop("partial_issues", None)
        for row in updated["sites"]:
            values = row["values"]
            row["values"] = {
                str(issue): values[str(issue)]
                for issue in updated["issues"]
                if str(issue) in values
            }
            failures = row.get("failures", {})
            row["failures"] = {
                str(issue): failures[str(issue)]
                for issue in updated["issues"]
                if str(issue) in failures
            }
        updated["updated_at"] = datetime.now(timezone.utc).isoformat()
        updated["last_run_id"] = run_id or uuid4().hex
        updated["parser_versions"] = parser_versions
        self.validate(
            updated,
            expected_site_count=expected_site_count,
            expected_site_names=expected_names,
        )
        return updated
