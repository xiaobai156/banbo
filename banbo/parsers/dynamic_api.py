from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from banbo.domain.models import (
    Document,
    DocumentSource,
    ParseEvidence,
    SiteSpec,
)
from banbo.domain import document_matches_record

from .history_block import HistoryBlockParser
from .protocol import ParserSpec


class DynamicApiParser:
    name = "dynamic_api"

    def __init__(self, spec: ParserSpec) -> None:
        self._spec = spec
        self.version = spec.parser_version

    def parse(
        self,
        site: SiteSpec,
        documents: Sequence[Document],
        target_issue: int,
    ) -> tuple[ParseEvidence, ...]:
        if site.expected_record_id is None:
            return ()
        scoped = tuple(
            document
            for document in documents
            if document.source in {
                DocumentSource.API,
                DocumentSource.BROWSER,
            }
            and document_matches_record(
                document,
                site.expected_record_id,
            )
        )
        if not scoped:
            return ()
        delegate = HistoryBlockParser(
            replace(self._spec, strategy="history_block")
        )
        return tuple(
            replace(
                item,
                parser_name=self.name,
                parser_version=self.version,
            )
            for item in delegate.parse(site, scoped, target_issue)
        )
