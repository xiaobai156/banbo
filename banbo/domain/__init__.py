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
from .validation import validate_evidence

__all__ = [
    "Direction",
    "Document",
    "DocumentSource",
    "FailureCode",
    "FailureResult",
    "ParseEvidence",
    "SiteSpec",
    "ValidatedResult",
    "ValidationOutcome",
    "validate_evidence",
]
