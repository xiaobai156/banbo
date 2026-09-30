from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence

from banbo.domain.models import Direction, Document, ParseEvidence, SiteSpec


@dataclass(frozen=True)
class ParserSpec:
    site_id: str
    strategy: str
    parser_version: str
    parser_id: str = ""
    direction: Direction | None = None
    anchors: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ("绝杀半波",)
    issue_pattern: str | None = None
    value_pattern: str | None = None
    before_documents: int = 0
    after_documents: int = 0
    target_only: bool = True
    record_id_pattern: str | None = None
    topic_id_pattern: str | None = None
    options: Mapping[str, object] = field(default_factory=dict)
    link_external_scripts_to_entry: bool = False


class SiteParser(Protocol):
    name: str
    version: str

    def parse(
        self,
        site: SiteSpec,
        documents: Sequence[Document],
        target_issue: int,
    ) -> tuple[ParseEvidence, ...]: ...
