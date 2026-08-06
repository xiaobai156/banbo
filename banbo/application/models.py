from __future__ import annotations

from dataclasses import dataclass

from banbo.domain.models import ValidatedResult, ValidationOutcome
from banbo.storage.site_repository import SiteRecord


@dataclass(frozen=True)
class SiteRun:
    site: SiteRecord
    outcome: ValidationOutcome
    elapsed_ms: int = 0
    document_count: int = 0
    request_url: str = ""

    @property
    def succeeded(self) -> bool:
        return isinstance(self.outcome, ValidatedResult)


@dataclass(frozen=True)
class ProgressUpdate:
    completed: int
    total: int
    succeeded: int
    failed: int
    elapsed_seconds: float
    site: SiteRecord
    target_issue: int
