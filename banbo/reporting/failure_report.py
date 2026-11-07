from __future__ import annotations

from collections.abc import Mapping

from banbo.domain import FailureCode
from banbo.domain.models import FailureResult

from banbo.application.models import SiteRun
from banbo.application.multi_period import MultiPeriodSiteResult
from banbo.storage.atomic_files import commit_files, read_text_snapshot
import re


_FAILURE_STAGES = {
    FailureCode.NETWORK_ERROR: "网络请求",
    FailureCode.SSL_ERROR: "网络请求",
    FailureCode.HTTP_ERROR: "网络请求",
    FailureCode.TARGET_PERIOD_MISSING: "指定期数校验",
    FailureCode.DIRECTION_MISMATCH: "指定期数校验",
    FailureCode.DIRECTION_WINDOW_INVALID: "指定期数校验",
    FailureCode.ANCHOR_MISSING: "目标定位",
    FailureCode.RECORD_ID_MISMATCH: "目标定位",
    FailureCode.DOCUMENT_BOUNDARY_MISMATCH: "目标定位",
    FailureCode.PARSER_SPEC_MISSING: "目标定位",
    FailureCode.FIELD_INVALID: "数据校验",
    FailureCode.SAME_PERIOD_CONFLICT: "数据校验",
    FailureCode.ADAPTIVE_MATCH_REJECTED: "自适应校验",
    FailureCode.INTERNAL_ERROR: "抓取/解析",
    FailureCode.MULTI_PERIOD_FAILED: "多期汇总",
}
# 失败目录里有两类记录：
#   失败 … 本次校验没有结果，需要重抓；
#   保留 … 本次校验失败，但该站该期已有定稿值，值不动、也不重抓。
# 只有「失败」会被 --retry-failures 选中。
_RECORD = re.compile(
    r"^(?P<kind>失败|保留) (?P<name>\S+) (?P<url>\S+) "
    r"方向: (?P<direction>top|bottom) 期数: (?P<period>\d+)"
)
_CONFLICT_MARKER = "拒绝覆盖"


def failure_site_names(text: str, period: int) -> tuple[str, ...]:
    """Sites with a real failure record (``保留`` records are not retryable)."""

    names: list[str] = []
    for line in text.splitlines():
        match = _RECORD.match(line.strip())
        if (
            match
            and match.group("kind") == "失败"
            and int(match.group("period")) == int(period)
            and match.group("name") not in names
        ):
            names.append(match.group("name"))
    return tuple(names)


def remove_successful_failures(text: str, period: int, successful_names: set[str]) -> str:
    if not successful_names:
        return text
    records: list[list[str]] = []
    prefix: list[str] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if _RECORD.match(line.strip()):
            if current is not None:
                records.append(current)
            current = [line]
        elif current is None:
            prefix.append(line)
        else:
            current.append(line)
    if current is not None:
        records.append(current)
    kept = prefix[:]
    for record in records:
        match = _RECORD.match(record[0].strip())
        if (
            not match
            or int(match.group("period")) != period
            or match.group("name") not in successful_names
        ):
            kept.extend(record)
    return "\n".join(kept).rstrip("\r\n") + ("\n" if kept else "")


def _failure_reason(failure: FailureResult) -> str:
    message = " ".join(failure.message.split())
    prefix = "新版流程异常："
    if failure.code == FailureCode.INTERNAL_ERROR and message.startswith(prefix):
        return f"抓取/解析失败({message[len(prefix):].strip()})"
    return message


def _format_failure_line(run: SiteRun) -> str:
    failure = run.outcome
    if not isinstance(failure, FailureResult):
        raise TypeError("只能格式化失败结果")
    return (
        f"失败 {run.site.name} {run.site.url} "
        f"方向: {run.site.direction.value} 期数: {failure.target_issue} "
        f"阶段: {_FAILURE_STAGES[failure.code]} "
        f"原因: {_failure_reason(failure)}"
    )


def _format_retained_line(run: SiteRun, note: str) -> str:
    """A failure that kept the already-final value instead of clearing it."""

    failure = run.outcome
    if not isinstance(failure, FailureResult):
        raise TypeError("只能格式化失败结果")
    reason = " ".join((note or "").split()) or "本次校验失败，已保留定稿值"
    return (
        f"保留 {run.site.name} {run.site.url} "
        f"方向: {run.site.direction.value} 期数: {failure.target_issue} "
        f"阶段: {_FAILURE_STAGES[failure.code]} "
        f"原因: {reason}"
    )


def _failure_blocks(runs: list[SiteRun]) -> list[str]:
    blocks: list[str] = []
    for run in runs:
        if not isinstance(run.outcome, FailureResult):
            continue
        blocks.append(_format_failure_line(run))
    return blocks


def _split_failure_records(text: str) -> tuple[list[str], list[list[str]]]:
    prefix: list[str] = []
    records: list[list[str]] = []
    current: list[str] | None = None
    for line in (text or "").splitlines():
        if _RECORD.match(line.strip()):
            if current is not None:
                records.append(current)
            current = [line]
        elif current is None:
            prefix.append(line)
        else:
            current.append(line)
    if current is not None:
        records.append(current)
    return prefix, records


def merge_failure_report(
    existing: str,
    period: int,
    runs: list[SiteRun],
    *,
    retained: Mapping[str, str] | None = None,
) -> str:
    """Merge this run's failures into the official failure TXT.

    Records of sites this run did not touch are kept verbatim, so a subset or
    retry run can no longer delete other sites' failure history.  A covered
    site gets its old record replaced by the current state, and a site listed
    in ``retained`` (name → note) is written as ``保留`` instead of ``失败``: it
    already holds a final value, so it must stay visible without being retried.
    """

    notes = {str(name): str(note) for name, note in (retained or {}).items()}
    covered = {run.site.name for run in runs}
    prefix, records = _split_failure_records(existing)
    blocks: list[str] = []
    if any(line.strip() for line in prefix):
        blocks.append("\n".join(prefix).strip("\r\n"))
    for record in records:
        match = _RECORD.match(record[0].strip())
        if (
            match
            and int(match.group("period")) == int(period)
            and match.group("name") in covered
        ):
            continue
        blocks.append("\n".join(record).strip("\r\n"))
    for run in runs:
        if not isinstance(run.outcome, FailureResult):
            continue
        note = notes.get(run.site.name)
        blocks.append(
            _format_retained_line(run, note)
            if note is not None
            else _format_failure_line(run)
        )
    kept = [block for block in blocks if block]
    if not kept:
        return ""
    return "\n\n".join(kept) + "\n"


def conflict_site_names(text: str, period: int) -> tuple[str, ...]:
    """Sites whose failure record is a "would overwrite a final value" conflict.

    Retrying those cannot help: the disagreement needs a human decision, so
    ``--retry-failures`` must not pick them up again.
    """

    names: list[str] = []
    for record in _split_failure_records(text)[1]:
        match = _RECORD.match(record[0].strip())
        if not match or int(match.group("period")) != int(period):
            continue
        if match.group("kind") != "失败":
            continue
        if match.group("name") in names:
            continue
        if _CONFLICT_MARKER in "\n".join(record):
            names.append(match.group("name"))
    return tuple(names)


def conflict_rejected_values(text: str, period: int) -> dict[str, str]:
    """The value the parser proposed and the record refused, per site.

    一轮冲突、一轮保留之后，失败TXT 里只剩「保留 … 上次拒绝的新值为X」，
    所以两种记录都要读；否则第二次保留就把那个值丢了。
    """

    rejected: dict[str, str] = {}
    for record in _split_failure_records(text)[1]:
        match = _RECORD.match(record[0].strip())
        if not match or int(match.group("period")) != int(period):
            continue
        body = "\n".join(record)
        found = re.search(r"->\s*([红绿蓝][单双])", body)
        if found is None:
            found = re.search(r"上次拒绝的新值为([红绿蓝][单双])", body)
        if found:
            rejected[match.group("name")] = found.group(1)
    return rejected


def render_failure_report(period: int, runs: list[SiteRun]) -> str:
    blocks = _failure_blocks(runs)
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


def write_failure_report(path: str, period: int, runs: list[SiteRun]) -> bool:
    """Merge into the official failure TXT; kept for callers that pass a path."""

    existing, _ = read_text_snapshot(path)
    content = merge_failure_report(existing, period, runs)
    commit_files({path: content or None})
    return bool(content)


def render_multi_failure_report(
    results: tuple[MultiPeriodSiteResult, ...],
    *,
    retained: Mapping[tuple[int, str], str] | None = None,
) -> str:
    """Every failed period of every site, including sites that passed elsewhere.

    A multi-period run is a per-period verification: a site that produced 288
    but failed 289 still has a real failure to report, so it is listed instead
    of being hidden behind the site-level "at least one period passed" flag.
    Sites that kept a final value are labelled ``保留`` here too, matching the
    per-period failure file.
    """

    notes = dict(retained or {})
    blocks: list[str] = []
    for result in results:
        for run in result.periods:
            if not isinstance(run.outcome, FailureResult):
                continue
            note = notes.get((int(run.outcome.target_issue), run.site.name))
            blocks.append(
                _format_retained_line(run, note)
                if note is not None
                else _format_failure_line(run)
            )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def write_multi_failure_report(path: str, results: tuple[MultiPeriodSiteResult, ...]) -> bool:
    content = render_multi_failure_report(results)
    commit_files({path: content or None})
    return bool(content)
