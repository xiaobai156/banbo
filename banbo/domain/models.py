from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TypeAlias

from .errors import FailureCode


class Direction(str, Enum):
    TOP = "top"
    BOTTOM = "bottom"


class DocumentSource(str, Enum):
    PAGE = "page"
    SCRIPT = "script"
    IFRAME = "iframe"
    API = "api"
    BROWSER = "browser"


@dataclass(frozen=True)
class SiteSpec:
    site_id: str
    name: str
    url: str
    direction: Direction
    strategy: str
    anchors: tuple[str, ...]
    parser_version: str
    before_documents: int = 0
    after_documents: int = 0
    target_only: bool = True
    record_id_pattern: str | None = None
    topic_id_pattern: str | None = None
    keywords: tuple[str, ...] = ("绝杀半波",)
    issue_pattern: str = r"(?P<issue>\d{1,4})期"
    value_pattern: str = (
        r"(?P<value>[红绿蓝](?:波)?[单双])"
    )
    anchor_mode: str = "all"
    expected_record_id: str | None = None


@dataclass(frozen=True)
class Document:
    document_id: str
    source: DocumentSource
    source_url: str
    order: int
    content: str
    record_id: str | None = None
    fetched_at: str = ""
    linked_record_id: str | None = None
    record_relation: str = "direct"


@dataclass(frozen=True)
class ParseEvidence:
    site_id: str
    target_issue: int
    value: str
    document_id: str
    document_source: DocumentSource
    document_order: int
    snippet: str
    parser_name: str
    parser_version: str
    direction: Direction
    anchor_passed: bool
    keyword_passed: bool
    same_record: bool
    record_id: str | None = None
    linked_record_id: str | None = None
    expected_record_id: str | None = None
    anchors: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    source_offset: int = 0
    candidate_count: int = 1
    conflict_values: tuple[str, ...] = ()
    boundary_issues: tuple[int, ...] = ()
    parser_id: str = ""
    source_url: str = ""
    block_id: str = ""
    block_start: int = 0
    block_end: int = 0
    document_relation: str = "same_document"


@dataclass(frozen=True)
class ValidatedResult:
    site_id: str
    site_name: str
    target_issue: int
    value: str
    direction: Direction
    evidence: ParseEvidence
    parser_version: str


@dataclass(frozen=True)
class FailureResult:
    site_id: str
    target_issue: int
    code: FailureCode
    message: str
    evidence: tuple[ParseEvidence, ...] = field(default_factory=tuple)


ValidationOutcome: TypeAlias = ValidatedResult | FailureResult
