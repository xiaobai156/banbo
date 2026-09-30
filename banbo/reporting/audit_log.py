from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from banbo.domain.models import FailureResult, ValidatedResult

from banbo.application.models import SiteRun


def audit_record(run: SiteRun, *, run_id: str) -> dict[str, object]:
    outcome = run.outcome
    evidence = (
        outcome.evidence
        if isinstance(outcome, ValidatedResult)
        else (outcome.evidence[0] if outcome.evidence else None)
    )
    return {
        "run_id": run_id,
        "site_id": run.site.site_id,
        "site_name": run.site.name,
        "target_issue": getattr(outcome, "target_issue", None),
        "direction": run.site.direction.value,
        "request_url": run.request_url or run.site.url,
        "document_count": run.document_count,
        "document_id": evidence.document_id if evidence else None,
        "document_source": evidence.document_source.value if evidence else None,
        "source_url": evidence.source_url if evidence else None,
        "article_id": evidence.record_id if evidence else None,
        "linked_article_id": (
            evidence.linked_record_id if evidence else None
        ),
        "block_id": evidence.block_id if evidence else None,
        "block_start": evidence.block_start if evidence else None,
        "block_end": evidence.block_end if evidence else None,
        "document_relation": evidence.document_relation if evidence else None,
        "anchors": evidence.anchors if evidence else (),
        "keywords": evidence.keywords if evidence else (),
        "boundary_issues": evidence.boundary_issues if evidence else (),
        "conflict_values": evidence.conflict_values if evidence else (),
        "parser_id": evidence.parser_id if evidence else None,
        "parser": evidence.parser_name if evidence else None,
        "parser_version": evidence.parser_version if evidence else None,
        "candidate_count": evidence.candidate_count if evidence else 0,
        "value": outcome.value if isinstance(outcome, ValidatedResult) else None,
        "failure_code": outcome.code.value if isinstance(outcome, FailureResult) else None,
        "failure_reason": outcome.message if isinstance(outcome, FailureResult) else None,
        "elapsed_ms": run.elapsed_ms,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def render_audit_jsonl(
    runs: list[SiteRun],
    *,
    run_id: str | None = None,
) -> str:
    identifier = run_id or uuid4().hex
    return "".join(
        json.dumps(audit_record(run, run_id=identifier), ensure_ascii=False)
        + "\n"
        for run in runs
    )


def append_audit_jsonl(existing: str, addition: str) -> str:
    if existing and not existing.endswith("\n"):
        raise ValueError("既有审计文件末尾不是完整JSONL记录")
    for line_number, line in enumerate(existing.splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"既有审计文件包含空行：第{line_number}行")
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"既有审计文件包含无效JSON：第{line_number}行"
            ) from exc
    return existing + addition
