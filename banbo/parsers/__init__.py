"""只消费Document并产出ParseEvidence的解析层。"""

from .protocol import ParserSpec, SiteParser
from .registry import ParserRegistry, ParserRegistryError, build_default_registry
from .specs import ParserSpecError, parse_parser_specs

__all__ = [
    "ParserRegistry",
    "ParserRegistryError",
    "ParserSpec",
    "SiteParser",
    "build_default_registry",
    "ParserSpecError",
    "parse_parser_specs",
]
