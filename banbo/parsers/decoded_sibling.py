from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import replace
from typing import Sequence

from banbo.domain.models import Document, ParseEvidence, SiteSpec
from banbo.domain.normalization import normalize_text

from .history_block import HistoryBlockParser
from .protocol import ParserSpec
from .regex_line import RegexLineParser


_DECODED_SUFFIX = re.compile(r"#decoded-\d+$", re.IGNORECASE)


class DecodedSiblingParser:
    """Parse related fragments decoded from one fetched script."""

    name = "decoded_sibling"

    def __init__(self, spec: ParserSpec) -> None:
        self._spec = spec
        self.version = spec.parser_version

    def parse(
        self,
        site: SiteSpec,
        documents: Sequence[Document],
        target_issue: int,
    ) -> tuple[ParseEvidence, ...]:
        groups: dict[str, list[Document]] = defaultdict(list)
        for document in documents:
            groups[self._parent_source(document)].append(document)

        anchors = self._spec.anchors or site.anchors
        anchor_mode = str(
            self._spec.options.get("anchor_mode", site.anchor_mode)
        ).casefold()
        delegate = self._delegate()
        evidence: list[ParseEvidence] = []
        seen: set[tuple[str, int, str]] = set()
        skip_keyword_check = bool(
            self._spec.options.get("skip_keyword_check", False)
        )
        delegate_site = (
            replace(
                site,
                anchors=(),
                keywords=() if skip_keyword_check else site.keywords,
            )
            if self._spec.options.get("patterns")
            else site
        )
        for siblings in groups.values():
            ordered = tuple(sorted(siblings, key=lambda item: item.order))
            combined = " ".join(
                normalize_text(document.content) for document in ordered
            )
            matches = [normalize_text(anchor) in combined for anchor in anchors]
            anchor_passed = (
                not anchors
                or (anchor_mode == "all" and all(matches))
                or (anchor_mode != "all" and any(matches))
            )
            if not anchor_passed:
                continue
            anchor_documents = tuple(
                document
                for document in ordered
                if self._document_has_any_anchor(document, anchors)
            )
            for item in delegate.parse(delegate_site, ordered, target_issue):
                key = (item.document_id, item.source_offset, item.value)
                if key in seen:
                    continue
                seen.add(key)
                candidate = next(
                    document
                    for document in ordered
                    if document.document_id == item.document_id
                )
                same_document = self._document_has_anchor(
                    candidate,
                    anchors,
                    anchor_mode,
                )
                evidence.append(
                    replace(
                        item,
                        parser_name=self.name,
                        parser_version=self.version,
                        anchor_passed=True,
                        same_record=any(
                            self._same_record(candidate, anchor, site)
                            for anchor in anchor_documents
                        ),
                        document_relation=(
                            "same_document"
                            if same_document
                            else "declared_neighbor_window"
                        ),
                        anchors=anchors,
                    )
                )
        return tuple(evidence)

    def _delegate(self):
        if self._spec.options.get("patterns"):
            return RegexLineParser(
                replace(
                    self._spec,
                    strategy="regex_line",
                    anchors=(),
                    keywords=(
                        ()
                        if self._spec.options.get("skip_keyword_check", False)
                        else self._spec.keywords
                    ),
                )
            )
        delegate_options = dict(self._spec.options)
        delegate_options["skip_document_anchor"] = True
        return HistoryBlockParser(
            replace(
                self._spec,
                strategy="history_block",
                options=delegate_options,
            )
        )

    @staticmethod
    def _parent_source(document: Document) -> str:
        source_url = document.source_url
        if _DECODED_SUFFIX.search(source_url):
            return _DECODED_SUFFIX.sub("", source_url)
        return f"{source_url}\0{document.document_id}"

    @staticmethod
    def _document_has_anchor(
        document: Document,
        anchors: tuple[str, ...],
        anchor_mode: str,
    ) -> bool:
        if not anchors:
            return True
        normalized = normalize_text(document.content)
        matches = [normalize_text(anchor) in normalized for anchor in anchors]
        return all(matches) if anchor_mode == "all" else any(matches)

    @staticmethod
    def _document_has_any_anchor(
        document: Document,
        anchors: tuple[str, ...],
    ) -> bool:
        if not anchors:
            return True
        normalized = normalize_text(document.content)
        return any(normalize_text(anchor) in normalized for anchor in anchors)

    @staticmethod
    def _same_record(
        candidate: Document,
        anchor: Document,
        site: SiteSpec,
    ) -> bool:
        if site.expected_record_id is not None:
            return (
                candidate.record_id == site.expected_record_id
                and anchor.record_id == site.expected_record_id
            )
        if candidate.record_id is None and anchor.record_id is None:
            return True
        return candidate.record_id == anchor.record_id
