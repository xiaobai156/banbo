from __future__ import annotations

from pathlib import Path

from banbo.domain import FailureCode
from banbo.domain.models import FailureResult

from banbo.application.models import SiteRun
from banbo.application.multi_period import MultiPeriodSiteResult
from banbo.storage.atomic_files import commit_files


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


def write_failure_report(
    path: str | Path,
    period: int,
    runs: list[SiteRun],
) -> bool:
    content = render_failure_report(period, runs)
    target = Path(path)
    commit_files({target: content or None})
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


def write_multi_failure_report(
    path: str | Path,
    results: tuple[MultiPeriodSiteResult, ...],
) -> bool:
    content = render_multi_failure_report(results)
    target = Path(path)
    commit_files({target: content or None})
    return bool(content)
