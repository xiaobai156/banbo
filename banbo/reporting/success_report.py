from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
import re

from banbo.domain.models import ValidatedResult

from banbo.application.models import SiteRun
from banbo.storage.atomic_files import commit_files, read_text_snapshot


_SUCCESS_ROW = re.compile(r"^(?P<value>红单|红双|绿单|绿双|蓝单|蓝双)[ \t]+(?P<name>.+?)\s*$")
_RANKING_HEADER = re.compile(r"(?m)^(?:(?P<period>\d+)期排行|内容[ \t]+次数[ \t]+排名)[ \t]*\r?$")
_APPEND_RANKING_HEADER = re.compile(r"(?m)^内容[ \t]+次数[ \t]+排名[ \t]*\r?$")


@dataclass(frozen=True)
class SuccessConflict:
    """A freshly validated value that contradicts a value already on record."""

    site_name: str
    existing_values: tuple[str, ...]
    new_value: str
    source: str = "成功TXT"


@dataclass(frozen=True)
class SuccessMerge:
    """Result of merging one run into the official TXT.

    ``content``     the merged file text.
    ``conflicts``   unresolved disagreements; the caller records them as
                    failures instead of writing them.
    ``cache_align`` sites whose value the TXT and this run agree on while the
                    cache baseline differs: the cache is stale and should be
                    aligned to ``content``.
    ``replaced``    rows that ``--accept-verified`` overwrote, so the caller can
                    log exactly what changed.
    """

    content: str
    conflicts: tuple[SuccessConflict, ...] = ()
    cache_align: Mapping[str, str] = field(default_factory=dict)
    replaced: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    accepted: tuple[str, ...] = ()


def _split_success_report(
    existing: str,
    period: int,
) -> tuple[str, list[tuple[str, str]], str]:
    """Split the official TXT into rows and ranking, keeping the column order.

    Rows whose site is no longer in ``config/sites.json`` (hand-added or written
    by another tool) are kept as ordinary rows: the file is merged, never
    rebuilt from the current run alone.
    """

    text = existing or ""
    header = _RANKING_HEADER.search(text)
    if header and header.group("period") and int(header.group("period")) != period:
        raise ValueError(f"成功TXT期号与目标期不一致：{header.group('period')} != {period}")
    body = text[: header.start()] if header else text
    # 排行小节的形状沿用原文件：既有文件有的是「内容/次数/排名」，有的还带
    # 「N期排行」标题，完整渲染则是「排名/内容/数量」。日常运行不改用户看到
    # 的格式，所以按原文件的形状重排。
    style = "render"
    if header is not None and (
        _APPEND_RANKING_HEADER.match((header.group(0) or "").strip())
        or _APPEND_RANKING_HEADER.search(text, header.end())
    ):
        style = "append_period" if header.group("period") else "append_plain"
    rows: list[tuple[str, str]] = []
    for line in body.splitlines():
        match = _SUCCESS_ROW.match(line)
        if match:
            rows.append((match.group("value"), match.group("name")))
    return body, rows, style


def _render_ranking(period: int, rows: list[tuple[str, str]], style: str) -> str:
    counts = Counter(value for value, _ in rows)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if style == "append_period":
        lines = ["", f"{period}期排行", "内容\t次数\t排名"]
        lines += [
            f"{value}\t{count}\t{rank}"
            for rank, (value, count) in enumerate(ordered, start=1)
        ]
    elif style == "append_plain":
        lines = ["", "内容\t次数\t排名"]
        lines += [
            f"{value}\t{count}\t{rank}"
            for rank, (value, count) in enumerate(ordered, start=1)
        ]
    else:
        lines = ["", f"{period}期排行", "排名\t内容\t数量"]
        lines += [
            f"{rank}\t{value}\t{count}"
            for rank, (value, count) in enumerate(ordered, start=1)
        ]
    return "\n".join(lines) + "\n"


def merge_success_report(
    existing: str,
    period: int,
    runs: list[SiteRun],
    *,
    known_values: Mapping[str, str] | None = None,
    accept_verified: bool = False,
) -> SuccessMerge:
    """Merge this run's successes into the official TXT instead of replacing it.

    A site covered by this run has its row updated; a site that is absent from
    this run (subset run, retry, other tool) keeps its row untouched.  A site
    whose new value differs from the official record is *not* written: it is
    reported as a conflict, unless the operator explicitly passed
    ``accept_verified`` because the old value was wrong and the parser fix has
    just been re-verified.

    A covered site that failed keeps its existing row: one failed re-check must
    not delete a value that is already final (same rule as the cache layer).
    """

    successful = [
        run for run in runs if isinstance(run.outcome, ValidatedResult)
    ]
    if any(run.outcome.target_issue != int(period) for run in successful):
        raise ValueError("成功TXT目标期与结果期数不一致")
    body, rows, style = _split_success_report(existing, period)

    values_by_name: dict[str, set[str]] = {}
    for value, name in rows:
        values_by_name.setdefault(name, set()).add(value)
    duplicates = {
        name: values for name, values in values_by_name.items() if len(values) > 1
    }
    if duplicates:
        raise ValueError("成功TXT存在同名冲突：" + ",".join(sorted(duplicates)))

    known = {str(name): str(value) for name, value in (known_values or {}).items()}
    additions: list[tuple[str, str]] = []
    replacements: dict[str, str] = {}
    replaced: dict[str, tuple[str, ...]] = {}
    cache_align: dict[str, str] = {}
    conflicts: list[SuccessConflict] = []
    accepted: set[str] = set()

    def _conflict(
        name: str,
        held: tuple[str, ...],
        value: str,
        source: str,
    ) -> None:
        conflicts.append(
            SuccessConflict(
                site_name=name,
                existing_values=held,
                new_value=value,
                source=source,
            )
        )

    for run in successful:
        name = run.site.name
        value = run.outcome.value
        existing_values = values_by_name.get(name)
        cached = known.get(name)
        if existing_values:
            if existing_values == {value}:
                # TXT 与本次结果一致；缓存若不同，是缓存过期，按 TXT 对齐。
                if cached is not None and cached != value:
                    cache_align[name] = value
                continue
            if accept_verified:
                replacements[name] = value
                replaced[name] = tuple(sorted(existing_values))
                accepted.add(name)
                if cached is not None and cached != value:
                    cache_align[name] = value
                continue
            _conflict(name, tuple(sorted(existing_values)), value, "成功TXT")
            continue
        if cached is not None and cached != value:
            if accept_verified:
                additions.append((value, name))
                values_by_name[name] = {value}
                cache_align[name] = value
                accepted.add(name)
                continue
            _conflict(name, (cached,), value, "缓存")
            continue
        additions.append((value, name))
        values_by_name[name] = {value}

    if not additions and not replacements:
        return SuccessMerge(
            content=existing or "",
            conflicts=tuple(conflicts),
            cache_align=cache_align,
            replaced=replaced,
            accepted=tuple(sorted(accepted)),
        )

    if replacements:
        lines = body.splitlines()
        for index, line in enumerate(lines):
            match = _SUCCESS_ROW.match(line)
            if match and match.group("name") in replacements:
                name = match.group("name")
                lines[index] = f"{replacements[name]}\t{name}"
        body = "\n".join(lines)
        rows = [
            (replacements.get(name, value), name) for value, name in rows
        ]

    merged_rows = list(rows) + list(additions)
    parts: list[str] = []
    text = body.rstrip("\r\n")
    if text:
        parts.append(text)
    if additions:
        parts.append("\n".join(f"{value}\t{name}" for value, name in additions))
    merged = "\n".join(parts)
    return SuccessMerge(
        content=merged + ("\n" if merged else "") + _render_ranking(period, merged_rows, style),
        conflicts=tuple(conflicts),
        cache_align=cache_align,
        replaced=replaced,
        accepted=tuple(sorted(accepted)),
    )


def success_rows(content: str, period: int) -> tuple[tuple[str, str], ...]:
    """(value, site name) rows of the official TXT, ranking excluded."""

    _, rows, _ = _split_success_report(content, period)
    return tuple(rows)


def success_row_names(content: str, period: int) -> tuple[str, ...]:
    """Sites that already hold a final value in the official TXT for one period."""

    return tuple(name for _, name in success_rows(content, period))


def append_repair_successes(existing: str, runs: list[SiteRun]) -> str:
    successful = [
        run for run in runs if isinstance(run.outcome, ValidatedResult)
    ]
    if not successful:
        return existing
    period = successful[0].outcome.target_issue
    merge = merge_success_report(existing, period, runs)
    if merge.conflicts:
        conflict = merge.conflicts[0]
        raise ValueError(
            f"{conflict.source}中{conflict.site_name}已有不同结果："
            + ",".join(conflict.existing_values)
        )
    return merge.content


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


def write_success_report(path: str, period: int, runs: list[SiteRun]) -> bool:
    """Merge into the official TXT; kept for callers that pass only a path."""

    existing, _ = read_text_snapshot(path)
    merge = merge_success_report(existing, period, runs)
    if merge.conflicts:
        conflict = merge.conflicts[0]
        raise ValueError(
            f"{conflict.source}中{conflict.site_name}已有不同结果："
            + ",".join(conflict.existing_values)
        )
    commit_files({path: merge.content or None})
    return True
