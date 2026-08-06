from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from banbo.domain.models import Document, ParseEvidence, SiteSpec
from banbo.domain.normalization import normalize_text

from .history_block import HistoryBlockParser
from .protocol import ParserSpec


class TitleNeighborParser:
    name = "title_neighbor"

    def __init__(self, spec: ParserSpec) -> None:
        self._spec = spec
        self.version = spec.parser_version

    def parse(
        self,
        site: SiteSpec,
        documents: Sequence[Document],
        target_issue: int,
    ) -> tuple[ParseEvidence, ...]:
        anchors = self._spec.anchors or site.anchors
        anchor_mode = str(
            self._spec.options.get("anchor_mode", site.anchor_mode)
        ).casefold()
        anchor_indexes: list[int] = []
        for index, document in enumerate(documents):
            normalized = normalize_text(document.content)
            matches = [
                normalize_text(anchor) in normalized for anchor in anchors
            ]
            if (
                not anchors
                or (anchor_mode == "all" and all(matches))
                or (anchor_mode != "all" and any(matches))
            ):
                anchor_indexes.append(index)
        if not anchor_indexes:
            return ()

        anchor_indexes = (
            anchor_indexes[-3:]
            if site.direction.value == "bottom"
            else anchor_indexes[:3]
        )
        scoped: dict[str, Document] = {}
        anchors_by_document: dict[str, list[Document]] = {}
        before = max(0, self._spec.before_documents)
        after = max(0, self._spec.after_documents)
        for anchor_index in anchor_indexes:
            anchor_document = documents[anchor_index]
            start = max(0, anchor_index - before)
            stop = min(len(documents), anchor_index + after + 1)
            for document in documents[start:stop]:
                if document.document_id == anchor_document.document_id:
                    continue
                scoped[document.document_id] = document
                anchors_by_document.setdefault(
                    document.document_id, []
                ).append(anchor_document)
        if not scoped:
            return ()

        delegate_options = dict(self._spec.options)
        delegate_options["skip_document_anchor"] = True
        delegate = HistoryBlockParser(
            replace(
                self._spec,
                strategy="history_block",
                options=delegate_options,
            )
        )
        raw_evidence = delegate.parse(
            site,
            tuple(sorted(scoped.values(), key=lambda item: item.order)),
            target_issue,
        )
        evidence: list[ParseEvidence] = []
        seen: set[tuple[str, int, str]] = set()
        for item in raw_evidence:
            key = (item.document_id, item.source_offset, item.value)
            if key in seen:
                continue
            seen.add(key)
            candidate_document = scoped[item.document_id]
            anchor_documents = anchors_by_document[item.document_id]
            same_record = any(
                self._same_record(candidate_document, anchor_document, site)
                for anchor_document in anchor_documents
            )
            document_relation = (
                "same_document"
                if any(
                    candidate_document.document_id == anchor_document.document_id
                    for anchor_document in anchor_documents
                )
                else "declared_neighbor_window"
            )
            evidence.append(
                replace(
                    item,
                    parser_name=self.name,
                    parser_version=self.version,
                    anchor_passed=True,
                    same_record=same_record,
                    document_relation=document_relation,
                    anchors=anchors,
                )
            )
        return tuple(evidence)

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
