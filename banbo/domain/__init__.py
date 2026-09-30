"""与网络、解析器、缓存和输出隔离的领域模型。"""

from .errors import FailureCode
from .models import (
    Direction,
    Document,
    DocumentSource,
    FailureResult,
    ParseEvidence,
    SiteSpec,
    ValidatedResult,
    ValidationOutcome,
)
from .record_identity import document_matches_record, documents_share_record
from .validation import validate_evidence

__all__ = [
    "Direction",
    "Document",
    "DocumentSource",
    "document_matches_record",
    "documents_share_record",
    "FailureCode",
    "FailureResult",
    "ParseEvidence",
    "SiteSpec",
    "ValidatedResult",
    "ValidationOutcome",
    "validate_evidence",
]
