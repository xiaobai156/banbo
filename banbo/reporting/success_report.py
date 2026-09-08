from __future__ import annotations

from collections import Counter
import re

from banbo.domain.models import ValidatedResult

from banbo.application.models import SiteRun


_SUCCESS_ROW = re.compile(r"^(?P<value>红单|红双|绿单|绿双|蓝单|蓝双)[ \t]+(?P<name>.+?)\s*$")
_RANKING_HEADER = re.compile(r"(?m)^\d+期排行[ \t]*\r?$")


def append_repair_successes(existing: str, runs: list[SiteRun]) -> str:
    successful = [
        run for run in runs if isinstance(run.outcome, ValidatedResult)
    ]
    if not successful:
        return existing
    period = successful[0].outcome.target_issue

    values_by_name = {m.group("name"): m.group("value") for line in existing.splitlines() if (m := _SUCCESS_ROW.match(line))}

    additions: list[str] = []
    for run in successful:
        value = run.outcome.value
        existing_value = values_by_name.get(run.site.name)
        if existing_value:
            if existing_value != value:
                raise ValueError(
                    f"成功TXT中{run.site.name}已有不同结果："
                    + ",".join(sorted(existing_values))
                )
            continue
        additions.append(f"{value}\t{run.site.name}")
        values_by_name[run.site.name] = value

    if not additions:
        return existing
    rows = [(value, name) for name, value in values_by_name.items()]
    return _render_rows(period, rows)


def _render_rows(period: int, rows: list[tuple[str, str]]) -> str:
    lines = [f"{value}\t{name}" for value, name in rows]
    counts = Counter(value for value, _ in rows)
    lines += ["", f"{period}期排行", "排名\t内容\t数量"]
    lines += [f"{rank}\t{value}\t{count}" for rank, (value, count) in enumerate(sorted(counts.items(), key=lambda item: (-item[1], item[0])), 1)]
    return "\n".join(lines) + "\n"


def render_success_report(
    period: int,
    runs: list[SiteRun],
    *,
    extra_names: tuple[str, ...] = (),
) -> str:
    successful = [
        run for run in runs if isinstance(run.outcome, ValidatedResult)
    ]
    lines = [f"{run.outcome.value}\t{run.site.name}" for run in successful]
    lines.extend(extra_names)
    counts = Counter(run.outcome.value for run in successful)
    lines.extend(
        (
            "",
            f"{period}期排行",
            "排名\t内容\t数量",
        )
    )
    for rank, (value, count) in enumerate(
        sorted(counts.items(), key=lambda item: (-item[1], item[0])),
        start=1,
    ):
        lines.append(f"{rank}\t{value}\t{count}")
    return "\n".join(lines) + "\n"
