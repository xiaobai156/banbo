"""网络请求与原始文档发现层。"""

from .browser_client import BrowserClient
from .article_list import (
    ArticleListResolutionError,
    ArticleListSpec,
    ResolvedArticle,
    resolve_article_from_list,
)
from .document_discovery import (
    DiscoveryOptions,
    DocumentDiscoverer,
    DocumentRequest,
)
from .dynamic_records import (
    RecordBoundaryError,
    RecordBoundarySpec,
    ResolvedRecord,
    extract_record_id,
    resolve_unique_record,
)
from .dynamic_source import (
    DynamicSourceError,
    DynamicSourceSpec,
    fetch_dynamic_document,
)
from .http_client import FetchError, FetchResponse, HttpClient

__all__ = [
    "ArticleListResolutionError",
    "ArticleListSpec",
    "DiscoveryOptions",
    "BrowserClient",
    "DocumentDiscoverer",
    "DocumentRequest",
    "FetchError",
    "FetchResponse",
    "HttpClient",
    "RecordBoundaryError",
    "RecordBoundarySpec",
    "ResolvedArticle",
    "ResolvedRecord",
    "extract_record_id",
    "resolve_unique_record",
    "DynamicSourceError",
    "DynamicSourceSpec",
    "fetch_dynamic_document",
    "resolve_article_from_list",
]
