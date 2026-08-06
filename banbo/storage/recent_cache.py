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

from .atomic_files import atomic_write_json


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

    @staticmethod
    def validate(
        payload: Mapping[str, object],
        *,
        expected_site_count: int | None = None,
        expected_site_names: Iterable[str] | None = None,
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
            issue_numbers = {int(issue) for issue in issues}
        except (TypeError, ValueError) as exc:
            raise CacheValidationError("缓存期数格式无效") from exc
        if len(issue_numbers) != len(issues):
            raise CacheValidationError("缓存期数重复")
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
                if issue_number not in issue_numbers:
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
                if issue_number not in issue_numbers:
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
        if expected_site_names is not None:
            expected_names = {str(name) for name in expected_site_names}
            if names != expected_names:
                raise CacheValidationError("缓存站点集合与正式站点不一致")

    def update_existing_period(
        self,
        results: Iterable[ValidatedResult],
        *,
        site_names_by_id: Mapping[str, str],
        target_issue: int,
        run_id: str | None = None,
        expected_site_count: int | None = None,
        expected_site_names: Iterable[str] | None = None,
    ) -> dict:
        expected_names = (
            None
            if expected_site_names is None
            else tuple(str(name) for name in expected_site_names)
        )
        snapshot = self.load_snapshot(
            expected_site_count=expected_site_count,
            expected_site_names=expected_names,
        )
        updated = self.prepare_existing_period(
            results,
            site_names_by_id=site_names_by_id,
            target_issue=target_issue,
            run_id=run_id,
            base_payload=snapshot.payload,
            expected_site_count=expected_site_count,
            expected_site_names=expected_names,
        )
        atomic_write_json(
            self.path,
            updated,
            backup=True,
            expected_digest=snapshot.digest,
        )
        return updated

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

    def advance_complete_period(
        self,
        results: Iterable[ValidatedResult | FailureResult],
        *,
        site_names_by_id: Mapping[str, str],
        target_issue: int,
        expected_site_count: int,
        run_id: str | None = None,
        expected_site_names: Iterable[str] | None = None,
    ) -> dict:
        expected_names = (
            None
            if expected_site_names is None
            else tuple(str(name) for name in expected_site_names)
        )
        snapshot = self.load_snapshot(
            expected_site_count=expected_site_count,
            expected_site_names=expected_names,
        )
        updated = self.prepare_advance_complete_period(
            results,
            site_names_by_id=site_names_by_id,
            target_issue=target_issue,
            expected_site_count=expected_site_count,
            run_id=run_id,
            base_payload=snapshot.payload,
            expected_site_names=expected_names,
        )
        atomic_write_json(
            self.path,
            updated,
            backup=True,
            expected_digest=snapshot.digest,
        )
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
