from __future__ import annotations

from banbo.domain import FailureCode
from banbo.domain.models import FailureResult

from banbo.application.models import SiteRun
from banbo.application.multi_period import MultiPeriodSiteResult
from banbo.storage.atomic_files import commit_files
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
_FAILURE_SITE = re.compile(r"^失败 (?P<name>\S+) (?P<url>\S+) 方向: (?P<direction>top|bottom) 期数: (?P<period>\d+)")


def failure_site_names(text: str, period: int) -> tuple[str, ...]:
    names: list[str] = []
    for line in text.splitlines():
        match = _FAILURE_SITE.match(line.strip())
        if match and int(match.group("period")) == period and match.group("name") not in names:
            names.append(match.group("name"))
    return tuple(names)


def remove_successful_failures(text: str, period: int, successful_names: set[str]) -> str:
    if not successful_names:
        return text
    records: list[list[str]] = []
    prefix: list[str] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if _FAILURE_SITE.match(line.strip()):
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
        match = _FAILURE_SITE.match(record[0].strip())
        if not match or int(match.group("period")) != period or match.group("name") not in successful_names:
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


def render_failure_report(period: int, runs: list[SiteRun]) -> str:
    blocks: list[str] = []
    for run in runs:
        if not isinstance(run.outcome, FailureResult):
            continue
        blocks.append(_format_failure_line(run))
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


def write_failure_report(path: str, period: int, runs: list[SiteRun]) -> bool:
    content = render_failure_report(period, runs)
    commit_files({path: content or None})
    return bool(content)


def render_multi_failure_report(
    results: tuple[MultiPeriodSiteResult, ...],
) -> str:
    blocks: list[str] = []
    for result in results:
        if result.failure is None or not result.periods:
            continue
        for run in result.periods:
            if isinstance(run.outcome, FailureResult):
                blocks.append(_format_failure_line(run))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def write_multi_failure_report(path: str, results: tuple[MultiPeriodSiteResult, ...]) -> bool:
    content = render_multi_failure_report(results)
    commit_files({path: content or None})
    return bool(content)
