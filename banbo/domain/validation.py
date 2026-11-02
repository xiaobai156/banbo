from __future__ import annotations

import re
from collections.abc import Iterable

from .errors import FailureCode
from .models import (
    Direction,
    FailureResult,
    ParseEvidence,
    SiteSpec,
    ValidatedResult,
    ValidationOutcome,
)
from .normalization import normalize_half_wave


_PLACEHOLDER_DRAW = re.compile(
    r"开\s*[:：]?\s*(?:[0０]{2,}|[?？]{2,}|[0０]*[?？]+[0０]*[?？0０]*)"
)
_ISSUE_IN_SNIPPET = re.compile(r"(\d{2,4})\s*期")


def _is_placeholder_row(evidence: ParseEvidence) -> bool:
    """Whether the row still has an undrawn placeholder such as ``开:0000``.

    The requested period is the current one, so its draw number cannot exist
    yet: the authoritative row reads ``开:0000`` / ``开?00``.  Sites also carry
    a history table that sometimes labels its newest settled row with the
    current period by mistake, and that row does have a real draw number
    (``开:羊23准``).  Because a period that has not been drawn cannot carry a
    draw number, the placeholder row wins and the drawn row is mislabelled
    history.
    """

    return bool(_PLACEHOLDER_DRAW.search(evidence.snippet or ""))


def _span(evidence: ParseEvidence, target_issue: int) -> int:
    """Number of distinct periods the snippet enumerates (0 when unknown)."""

    snippet = evidence.snippet or ""
    issues = {int(match.group(1)) for match in _ISSUE_IN_SNIPPET.finditer(snippet)}
    if target_issue not in issues:
        return 0
    return len(issues)


def _sits_at_live_edge(
    evidence: ParseEvidence,
    target_issue: int,
    direction: Direction,
) -> bool:
    """Whether the snippet puts the target at the edge the direction reads from.

    ``bottom`` sites publish newest last, so the live block ends at the target;
    ``top`` sites publish newest first, so it starts at the target.  Used only to
    break a tie when two overlapping blocks cover the target with the same span
    (不言不语 301: 旧年度表 301..307 给蓝双，当期表 293..301 给蓝单，取后者).
    """

    snippet = evidence.snippet or ""
    issues = [int(match.group(1)) for match in _ISSUE_IN_SNIPPET.finditer(snippet)]
    if target_issue not in issues:
        return False
    if direction is Direction.BOTTOM:
        return issues[-1] == target_issue
    return issues[0] == target_issue


def _boundary_is_strict(
    boundary_issues: tuple[int, ...],
    target_issue: int,
    direction: Direction,
) -> bool:
    """Check the boundary is a coherent, monotonic window containing the target.

    The window must contain the target period and be monotonic.  Period gaps
    are allowed because sites skip unpublished periods, and a page that
    exposes only the current period yields a single-group window, so the length
    is capped rather than padded.

    ``direction`` is accepted for signature symmetry with the site spec; the
    window itself is computed by the parsers from the page order, and a page
    may list periods ascending or descending regardless of whether the site
    picks its value from the top or the bottom.  Enforcing "neighbours must sit
    on one side of the target" here would reject legitimate windows such as
    ``(288, 287, 286)`` when 287 is the requested period, so the direction
    check is not repeated at this layer; anti-shift protection lives in the
    parser-level global window instead.
    """

    issues = tuple(boundary_issues)
    if direction not in (Direction.TOP, Direction.BOTTOM):
        return False
    if not issues or len(issues) > 3 or target_issue not in issues:
        return False
    if len(issues) == 1:
        return True
    deltas = [issues[index + 1] - issues[index] for index in range(len(issues) - 1)]
    return all(delta > 0 for delta in deltas) or all(delta < 0 for delta in deltas)


def _failure(
    site: SiteSpec,
    target_issue: int,
    code: FailureCode,
    message: str,
    evidence: Iterable[ParseEvidence],
) -> FailureResult:
    return FailureResult(
        site_id=site.site_id,
        target_issue=target_issue,
        code=code,
        message=message,
        evidence=tuple(evidence),
    )


def validate_evidence(
    site: SiteSpec,
    target_issue: int,
    evidence: Iterable[ParseEvidence],
) -> ValidationOutcome:
    evidence_items = tuple(evidence)
    if any(item.site_id != site.site_id for item in evidence_items):
        return _failure(
            site,
            target_issue,
            FailureCode.INTERNAL_ERROR,
            "解析器返回了其它站点证据",
            evidence_items,
        )
    target_evidence = tuple(
        item for item in evidence_items if item.target_issue == target_issue
    )
    if site.target_only and any(
        item.target_issue != target_issue for item in evidence_items
    ):
        # target_only 表示只接受指定期的证据；解析器若把邻期结果一并返回，
        # 说明它在用相邻期凑数，直接判失败而不是悄悄过滤。
        return _failure(
            site,
            target_issue,
            FailureCode.TARGET_PERIOD_MISSING,
            f"仅允许{target_issue}期证据，解析器返回了其它期候选",
            tuple(
                item
                for item in evidence_items
                if item.target_issue != target_issue
            ),
        )
    if not target_evidence:
        return _failure(
            site,
            target_issue,
            FailureCode.TARGET_PERIOD_MISSING,
            f"未找到{target_issue}期专属证据",
            (),
        )

    if any(
        not item.boundary_issues
        or len(item.boundary_issues) > 3
        or target_issue not in item.boundary_issues
        for item in target_evidence
    ):
        return _failure(
            site,
            target_issue,
            FailureCode.DIRECTION_WINDOW_INVALID,
            "目标期不在严格顶部前三组或尾部后三组窗口内",
            target_evidence,
        )

    # 边界期必须由目标期出发、按站点方向严格连续，且目标期只能落在
    # 该方向的第 1 组：top 要求 target, target-1, target-2；bottom 要求
    # target, target+1, target+2。这能挡住「窗口整体平移」和「升序/跳期」
    # 两类跨期借值——解析器自填的 boundary_issues 不再被无条件信任。
    if any(
        not _boundary_is_strict(item.boundary_issues, target_issue, site.direction)
        for item in target_evidence
    ):
        return _failure(
            site,
            target_issue,
            FailureCode.DIRECTION_WINDOW_INVALID,
            "边界期未按方向严格连续，疑似窗口平移或跨期借值",
            target_evidence,
        )

    if any(
        not item.anchor_passed or not item.keyword_passed
        for item in target_evidence
    ):
        return _failure(
            site,
            target_issue,
            FailureCode.ANCHOR_MISSING,
            "专属锚点或关键词校验未通过",
            target_evidence,
        )

    if any(item.direction != site.direction for item in target_evidence):
        return _failure(
            site,
            target_issue,
            FailureCode.DIRECTION_MISMATCH,
            "候选位置方向与站点配置不一致",
            target_evidence,
        )

    if any(not item.same_record for item in target_evidence):
        return _failure(
            site,
            target_issue,
            FailureCode.DOCUMENT_BOUNDARY_MISMATCH,
            "标题与正文不属于同一记录或文档边界",
            target_evidence,
        )

    allowed_relations = {
        "same_document",
        "record_id",
        "declared_neighbor_window",
        "declared_nearest_document",
        "declared_split_document",
        "declared_entry_script",
    }
    if any(item.document_relation not in allowed_relations for item in target_evidence):
        return _failure(
            site,
            target_issue,
            FailureCode.DOCUMENT_BOUNDARY_MISMATCH,
            "文档关联关系未登记，拒绝跨文档拼接",
            target_evidence,
        )

    if any(
        item.expected_record_id is not None
        and item.record_id != item.expected_record_id
        and item.linked_record_id != item.expected_record_id
        for item in target_evidence
    ):
        return _failure(
            site,
            target_issue,
            FailureCode.RECORD_ID_MISMATCH,
            "URL记录ID与实际正文记录ID不一致",
            target_evidence,
        )

    # 目标期是当期、尚未开奖，所以带「开:0000 / 开?00」的行才是本期真值；
    # 带真实开奖号（开:羊23准）的同期行是历史表把最新一期错标成了当期。
    # 先用开奖字段挑出占位行，再判冲突；只有占位行不存在时才退回全部候选。
    pending = tuple(
        item for item in target_evidence if _is_placeholder_row(item)
    )
    decisive = pending if pending else target_evidence

    # 开奖字段被截断看不到时，用期号跨度判断：这类站同时发布两份重叠表，
    # 一份是不断向上累积的长档（如 291..299），一份是只覆盖最近几期的短块
    # （如 296..299）。短块每期重写，才是当期在用的那份——缓存历史可以证明：
    # 甜酸苦辣 298=绿单、贪生怕死 298=蓝双 都取自短块。所以同期出现多份时，
    # 只保留期号跨度最短的那批。
    if not pending:
        spans = [_span(item, target_issue) for item in decisive]
        known = [span for span in spans if span > 0]
        if known:
            shortest = min(known)
            live = tuple(
                item
                for item, span in zip(decisive, spans)
                if span == shortest
            )
            if live:
                decisive = live

    # 跨度也相同时（两份重叠表都覆盖目标期、期数一样多），按方向取「当期所在
    # 那一端」：底部站点最新一期在表尾，顶部站点在表头。不言不语 301 就是这种
    # 情形——旧年度表 301..307 给蓝双，当期表 293..301 给蓝单，取后者。
    if not pending and len({normalize_half_wave(item.value) for item in decisive}) > 1:
        at_edge = tuple(
            item for item in decisive if _sits_at_live_edge(item, target_issue, site.direction)
        )
        if at_edge:
            decisive = at_edge

    normalized_values = tuple(
        normalize_half_wave(item.value) for item in decisive
    )
    if any(value is None for value in normalized_values):
        return _failure(
            site,
            target_issue,
            FailureCode.FIELD_INVALID,
            "半波字段格式无效",
            decisive,
        )

    unique_values = set(normalized_values)
    if len(unique_values) != 1:
        return _failure(
            site,
            target_issue,
            FailureCode.SAME_PERIOD_CONFLICT,
            "同期存在多个不同半波结果",
            decisive,
        )

    chosen = min(
        decisive,
        key=lambda item: (item.document_order, item.document_id),
    )
    return ValidatedResult(
        site_id=site.site_id,
        site_name=site.name,
        target_issue=target_issue,
        value=next(iter(unique_values)),
        direction=site.direction,
        evidence=chosen,
        parser_version=chosen.parser_version,
    )
