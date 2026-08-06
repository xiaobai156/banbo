from __future__ import annotations

from collections.abc import Iterable

from .errors import FailureCode
from .models import (
    FailureResult,
    ParseEvidence,
    SiteSpec,
    ValidatedResult,
    ValidationOutcome,
)
from .normalization import normalize_half_wave


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
        for item in target_evidence
    ):
        return _failure(
            site,
            target_issue,
            FailureCode.RECORD_ID_MISMATCH,
            "URL记录ID与实际正文记录ID不一致",
            target_evidence,
        )

    normalized_values = tuple(
        normalize_half_wave(item.value) for item in target_evidence
    )
    if any(value is None for value in normalized_values):
        return _failure(
            site,
            target_issue,
            FailureCode.FIELD_INVALID,
            "半波字段格式无效",
            target_evidence,
        )

    unique_values = set(normalized_values)
    if len(unique_values) != 1:
        return _failure(
            site,
            target_issue,
            FailureCode.SAME_PERIOD_CONFLICT,
            "同期存在多个不同半波结果",
            target_evidence,
        )

    chosen = min(
        target_evidence,
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
