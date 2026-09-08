from __future__ import annotations

from collections import Counter
import re

from banbo.domain.models import ValidatedResult

from banbo.application.models import SiteRun


_SUCCESS_ROW = re.compile(
    r"^(?P<value>红单|红双|绿单|绿双|蓝单|蓝双)\s+(?P<name>.+?)\s*$"
)
_RANKING_HEADER = re.compile(
    r"(?m)^(?:\d+期排行[ \t]*|内容[ \t]+次数[ \t]+排名[ \t]*)(?=\r?$)"
)


def append_repair_successes(existing: str, runs: list[SiteRun]) -> str:
    successful = [
        run for run in runs if isinstance(run.outcome, ValidatedResult)
    ]
    if not successful:
        return existing
    if not existing:
        raise ValueError("定向修复只能追加到已存在的当期成功TXT")

    values_by_name: dict[str, set[str]] = {}
    for line in existing.splitlines():
        match = _SUCCESS_ROW.match(line)
        if match is None:
            continue
        values_by_name.setdefault(match.group("name"), set()).add(
            match.group("value")
        )

    additions: list[str] = []
    for run in successful:
        value = run.outcome.value
        existing_values = values_by_name.get(run.site.name)
        if existing_values:
            if existing_values != {value}:
                raise ValueError(
                    f"成功TXT中{run.site.name}已有不同结果："
                    + ",".join(sorted(existing_values))
                )
            continue
        additions.append(f"{value} {run.site.name}")
        values_by_name[run.site.name] = {value}

    if not additions:
        return existing
    ranking = _RANKING_HEADER.search(existing)
    if ranking is None:
        raise ValueError("成功TXT缺少当期排行榜，拒绝错位追加")
    newline = "\r\n" if "\r\n" in existing else "\n"
    prefix = existing[: ranking.start()].rstrip("\r\n")
    suffix = existing[ranking.start() :].lstrip("\r\n")
    return (
        prefix
        + newline
        + newline.join(additions)
        + newline * 2
        + suffix
    )


def render_success_report(
    period: int,
    runs: list[SiteRun],
    *,
    extra_names: tuple[str, ...] = (),
) -> str:
    successful = [
        run for run in runs if isinstance(run.outcome, ValidatedResult)
    ]
    lines = [
        f"{run.outcome.value} {run.site.name}" for run in successful
    ]
    lines.extend(extra_names)
    counts = Counter(run.outcome.value for run in successful)
    lines.extend(
        (
            "",
            "内容 次数 排名",
        )
    )
    for rank, (value, count) in enumerate(
        sorted(counts.items(), key=lambda item: (-item[1], item[0])),
        start=1,
    ):
        lines.append(f"{value} {count} {rank}")
    return "\n".join(lines) + "\n"
