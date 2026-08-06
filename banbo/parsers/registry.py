from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from banbo.domain.models import Document, ParseEvidence, SiteSpec

from .protocol import ParserSpec, SiteParser


class ParserRegistryError(RuntimeError):
    pass


ParserFactory = Callable[[ParserSpec], SiteParser]


class ParserRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, ParserFactory] = {}
        self._site_parsers: dict[str, SiteParser] = {}
        self._site_specs: dict[str, ParserSpec] = {}
        self._parser_ids: dict[str, str] = {}

    def register_strategy(
        self,
        strategy: str,
        factory: ParserFactory,
    ) -> None:
        if strategy in self._strategies:
            raise ParserRegistryError(f"解析策略重复注册：{strategy}")
        self._strategies[strategy] = factory

    def bind(self, spec: ParserSpec) -> None:
        if spec.site_id in self._site_parsers:
            raise ParserRegistryError(f"站点解析规格重复绑定：{spec.site_id}")
        parser_id = spec.parser_id or (
            f"{spec.site_id}:{spec.strategy}:v{spec.parser_version}"
        )
        if parser_id in self._parser_ids:
            raise ParserRegistryError(f"parser_id重复：{parser_id}")
        factory = self._strategies.get(spec.strategy)
        if factory is None:
            raise ParserRegistryError(f"解析策略未注册：{spec.strategy}")
        self._site_parsers[spec.site_id] = factory(spec)
        self._site_specs[spec.site_id] = replace(spec, parser_id=parser_id)
        self._parser_ids[parser_id] = spec.site_id

    def parser_for(self, site_id: str) -> SiteParser:
        parser = self._site_parsers.get(site_id)
        if parser is None:
            raise ParserRegistryError(f"站点没有专属解析规格：{site_id}")
        return parser

    def parse(
        self,
        site: SiteSpec,
        documents: Sequence[Document],
        target_issue: int,
    ) -> tuple[ParseEvidence, ...]:
        parser = self.parser_for(site.site_id)
        spec = self._site_specs[site.site_id]
        if spec.direction is not None and spec.direction != site.direction:
            raise ParserRegistryError(
                f"{site.site_id}解析规格方向与站点配置不一致"
            )
        evidence = tuple(parser.parse(site, documents, target_issue))
        if any(not isinstance(item, ParseEvidence) for item in evidence):
            raise ParserRegistryError(
                f"{site.site_id}解析器只能返回ParseEvidence"
            )
        if any(item.site_id != site.site_id for item in evidence):
            raise ParserRegistryError(
                f"{site.site_id}解析器返回了其它站点证据"
            )
        documents_by_id: dict[str, Document] = {}
        for document in documents:
            if document.document_id in documents_by_id:
                raise ParserRegistryError(
                    f"{site.site_id}文档ID重复：{document.document_id}"
                )
            documents_by_id[document.document_id] = document
        enriched: list[ParseEvidence] = []
        for item in evidence:
            document = documents_by_id.get(item.document_id)
            if document is None:
                raise ParserRegistryError(
                    f"{site.site_id}证据引用了未知文档：{item.document_id}"
                )
            block_start = max(0, item.source_offset)
            block_end = block_start + len(item.snippet)
            enriched.append(
                replace(
                    item,
                    source_url=document.source_url,
                    parser_id=spec.parser_id or (
                        f"{spec.site_id}:{spec.strategy}:v{spec.parser_version}"
                    ),
                    block_id=f"{document.document_id}:{block_start}:{block_end}",
                    block_start=block_start,
                    block_end=block_end,
                )
            )
        return tuple(enriched)


def build_default_registry() -> ParserRegistry:
    from .anchor_segment import AnchorSegmentParser
    from .article_sibling_segment import ArticleSiblingSegmentParser
    from .combined_sibling import CombinedSiblingParser
    from .dynamic_api import DynamicApiParser
    from .decoded_sibling import DecodedSiblingParser
    from .history_block import HistoryBlockParser
    from .nearest_document import NearestDocumentParser
    from .scoped_line import ScopedLineParser
    from .regex_line import RegexLineParser
    from .split_document import SplitDocumentParser
    from .table import TableParser
    from .title_neighbor import TitleNeighborParser

    registry = ParserRegistry()
    registry.register_strategy("anchor_segment", AnchorSegmentParser)
    registry.register_strategy(
        "article_sibling_segment", ArticleSiblingSegmentParser
    )
    registry.register_strategy("combined_sibling", CombinedSiblingParser)
    registry.register_strategy("history_block", HistoryBlockParser)
    registry.register_strategy("nearest_document", NearestDocumentParser)
    registry.register_strategy("scoped_line", ScopedLineParser)
    registry.register_strategy("regex_line", RegexLineParser)
    registry.register_strategy("title_neighbor", TitleNeighborParser)
    registry.register_strategy("split_document", SplitDocumentParser)
    registry.register_strategy("table", TableParser)
    registry.register_strategy("dynamic_api", DynamicApiParser)
    registry.register_strategy("decoded_sibling", DecodedSiblingParser)
    return registry
