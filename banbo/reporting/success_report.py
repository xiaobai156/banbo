from __future__ import annotations

from collections import Counter
from pathlib import Path

from banbo.domain.models import ValidatedResult

from banbo.application.models import SiteRun
from banbo.storage.atomic_files import atomic_write_text


def render_success_report(period: int, runs: list[SiteRun]) -> str:
    successful = [
        run for run in runs if isinstance(run.outcome, ValidatedResult)
    ]
    lines = [
        f"{run.outcome.value}\t{run.site.name}" for run in successful
    ]
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


def write_success_report(
    path: str | Path,
    period: int,
    runs: list[SiteRun],
) -> None:
    atomic_write_text(
        path,
        render_success_report(period, runs),
        backup=False,
    )
