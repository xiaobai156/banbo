from __future__ import annotations

import argparse
import json
from pathlib import Path

from banbo.application import detect_repeats
from banbo.domain.normalization import normalize_half_wave
from banbo.storage.atomic_files import atomic_write_json
from banbo.storage.recent_cache import RecentCacheRepository

from .cli import BASE_DIR, DEFAULT_CACHE_PATH, _load_runtime


def _parse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="杀半波新版重复检测入口")
    parser.add_argument(
        "--candidate",
        type=Path,
        default=BASE_DIR / "config" / "duplicate_candidate.json",
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--minimum-run", type=int, default=3)
    return parser


def _load_candidate(path: Path) -> tuple[str, dict[int, str]]:
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    else:
        name = input("请输入候选站名：").strip()
        raw_values = input("请输入期数和值，例如211=蓝单 210=红双：").split()
        payload = {
            "candidate_name": name,
            "values": {
                part.split("=", 1)[0]: part.split("=", 1)[1]
                for part in raw_values
                if "=" in part
            },
        }
    if not isinstance(payload, dict):
        raise ValueError("候选清单必须是JSON对象")
    name = str(payload.get("candidate_name", "")).strip()
    raw_values = payload.get("values")
    if not name or not isinstance(raw_values, dict) or not raw_values:
        raise ValueError("候选站名和有效期数数据不能为空")
    values: dict[int, str] = {}
    for raw_issue, raw_value in raw_values.items():
        value = normalize_half_wave(str(raw_value))
        if value is None:
            raise ValueError(f"候选半波无效：{raw_issue}={raw_value}")
        values[int(raw_issue)] = value
    return name, values


def main(argv: list[str] | None = None) -> int:
    args = _parse().parse_args(argv)
    candidate_name, candidate_values = _load_candidate(args.candidate)
    sites, specs, _ = _load_runtime()
    cache = RecentCacheRepository(args.cache).load_snapshot_for_sites(
        (
            {
                "name": site.name,
                "url": site.url,
                "pick": site.direction.value,
                "second_click": site.second_click,
            }
            for site in sites.all()
        ),
        expected_parser_versions={
            spec.site_id: spec.parser_version for spec in specs
        },
    ).payload
    existing = {
        site["name"]: site["values"]
        for site in cache["sites"]
        if site.get("values")
    }
    findings = detect_repeats(
        candidate_values,
        existing,
        minimum_run=max(3, args.minimum_run),
        candidate_name=candidate_name,
    )
    report = {
        "candidate_name": candidate_name,
        "candidate_values": {str(k): v for k, v in sorted(candidate_values.items(), reverse=True)},
        "findings": [
            {
                "existing_name": item.existing_name,
                "run_length": item.run_length,
                "issues": list(item.issues),
                "value": item.value,
                "decision": "reject" if item.run_length >= 6 else "manual_review",
            }
            for item in findings
        ],
    }
    output = BASE_DIR / "evidence" / "duplicate_check_latest.json"
    atomic_write_json(output, report)
    if not findings:
        print("未发现连续3期以上重复，可进入后续专属验证。")
        return 0
    for item in findings:
        decision = "拒收" if item.run_length >= 6 else "人工审核"
        print(
            f"{decision}：{item.existing_name}，连续{item.run_length}期，"
            f"期数={','.join(map(str, item.issues))}，值={item.value}"
        )
    return 1 if any(item.run_length >= 6 for item in findings) else 2


if __name__ == "__main__":
    raise SystemExit(main())
