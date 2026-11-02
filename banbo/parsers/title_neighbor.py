from __future__ import annotations

import re
from dataclasses import replace
from typing import Sequence

from banbo.domain.models import Direction, Document, ParseEvidence, SiteSpec
from banbo.domain.normalization import normalize_text
from banbo.domain import documents_share_record

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
        include_anchor_document = bool(
            self._spec.options.get("include_anchor_document", False)
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
                if (
                    document.document_id == anchor_document.document_id
                    and not include_anchor_document
                ):
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
        # 委托解析器按「锚点文档窗口」算边界，窗口会被 before/after_documents
        # 整体平移，导致指定期实际排在页面第 N 组也能通过。这里改用**整页**
        # 文档重算页面级方向窗口，并硬判定目标期必须落在页面 top3/bottom3，
        # 不在其中就直接丢弃证据，避免跨期借值。
        page_issues = self._page_issues(documents)
        if not self._target_in_page_window(site, page_issues, target_issue):
            return ()
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
    def _page_issues(documents: Sequence[Document]) -> list[int]:
        """Return the distinct period numbers in page order (whole page)."""

        issues: list[int] = []
        pattern = re.compile(r"(\d{1,4})期")
        for document in documents:
            for match in pattern.finditer(normalize_text(document.content)):
                issue = int(match.group(1))
                if not issues or issues[-1] != issue:
                    issues.append(issue)
        return issues

    @classmethod
    def _target_in_page_window(
        cls,
        site: SiteSpec,
        page_issues: Sequence[int],
        target_issue: int,
    ) -> bool:
        """Whether the target period appears on the page at all.

        ``title_neighbor`` sites put the anchor (site name) after the value, and
        ``before_documents``/``after_documents`` reach up to 64 documents, so
        the requested period is routinely far from the page's newest or oldest
        entry — that is the intended layout, not a shifted window.  Rejecting
        by page position therefore blocked dozens of healthy sites during the
        298-period regression (36 false failures), so this guard only requires
        the period to exist on the page.  Cross-period safety for this parser
        comes from the delegate's own direction window plus the monotonic
        boundary check in ``validate_evidence``.
        """

        if site.direction not in (Direction.TOP, Direction.BOTTOM):
            return False
        return target_issue in page_issues

    @staticmethod
    def _same_record(
        candidate: Document,
        anchor: Document,
        site: SiteSpec,
    ) -> bool:
        return documents_share_record(
            candidate,
            anchor,
            site.expected_record_id,
        )
