from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from banbo.domain.models import Document, ParseEvidence, SiteSpec
from banbo.domain.normalization import normalize_text

from .history_block import HistoryBlockParser
from .protocol import ParserSpec


class NearestDocumentParser:
    name = "nearest_document"

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
        require_target = bool(
            self._spec.options.get("require_target_in_anchor", False)
        )
        side = str(
            self._spec.options.get("candidate_side", "both")
        ).casefold()
        anchor_indexes: list[int] = []
        for index, document in enumerate(documents):
            normalized = normalize_text(document.content)
            matches = [
                normalize_text(anchor) in normalized for anchor in anchors
            ]
            anchor_passed = (
                not anchors
                or (anchor_mode == "all" and all(matches))
                or (anchor_mode != "all" and any(matches))
            )
            if not anchor_passed:
                continue
            if require_target and f"{target_issue}期" not in normalized:
                continue
            anchor_indexes.append(index)
        if not anchor_indexes:
            return ()

        anchor_indexes = (
            anchor_indexes[-3:]
            if site.direction.value == "bottom"
            else anchor_indexes[:3]
        )

        delegate_options = dict(self._spec.options)
        delegate_options.update(
            {"skip_document_anchor": True, "target_only_scope": True}
        )
        delegate = HistoryBlockParser(
            replace(
                self._spec,
                strategy="history_block",
                options=delegate_options,
            )
        )
        collected: list[tuple[int, int, ParseEvidence, Document]] = []
        for anchor_index in anchor_indexes:
            anchor_document = documents[anchor_index]
            start = max(0, anchor_index - self._spec.before_documents)
            stop = min(
                len(documents),
                anchor_index + self._spec.after_documents + 1,
            )
            for document_index in range(start, stop):
                if side == "before" and document_index >= anchor_index:
                    continue
                if side == "after" and document_index <= anchor_index:
                    continue
                document = documents[document_index]
                evidence = delegate.parse(site, (document,), target_issue)
                for item in evidence:
                    collected.append(
                        (
                            abs(document_index - anchor_index),
                            anchor_index,
                            item,
                            anchor_document,
                        )
                    )
        if not collected:
            return ()

        nearest_distance = min(item[0] for item in collected)
        nearest = [item for item in collected if item[0] == nearest_distance]
        conflict_values = tuple(
            sorted({item[2].value for item in nearest})
        )
        evidence: list[ParseEvidence] = []
        seen: set[tuple[str, int, str]] = set()
        for _, _, item, anchor_document in nearest:
            key = (item.document_id, item.source_offset, item.value)
            if key in seen:
                continue
            seen.add(key)
            candidate_document = next(
                document
                for document in documents
                if document.document_id == item.document_id
            )
            evidence.append(
                replace(
                    item,
                    parser_name=self.name,
                    parser_version=self.version,
                    anchor_passed=True,
                    same_record=self._same_record(
                        candidate_document,
                        anchor_document,
                        site,
                    ),
                    document_relation=(
                        "same_document"
                        if candidate_document.document_id
                        == anchor_document.document_id
                        else "declared_nearest_document"
                    ),
                    anchors=anchors,
                    candidate_count=len(nearest),
                    conflict_values=conflict_values,
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
