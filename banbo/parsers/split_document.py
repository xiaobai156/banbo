from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from banbo.domain.models import (
    Direction,
    Document,
    ParseEvidence,
    SiteSpec,
)
from banbo.domain.normalization import normalize_half_wave, normalize_text

from .protocol import ParserSpec
from .text import html_to_text


@dataclass(frozen=True)
class _ValueCandidate:
    value: str
    document: Document
    offset: int
    snippet: str
    anchor_document: Document


class SplitDocumentParser:
    name = "split_document"

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
        keywords = self._spec.keywords or site.keywords
        issue_regex = re.compile(
            self._spec.issue_pattern or site.issue_pattern,
            re.IGNORECASE,
        )
        value_regex = re.compile(
            self._spec.value_pattern or site.value_pattern,
            re.IGNORECASE,
        )
        anchor_indexes = []
        for index, document in enumerate(documents):
            normalized = normalize_text(document.content)
            if anchors and not all(
                normalize_text(anchor) in normalized for anchor in anchors
            ):
                continue
            issues = self._issues(issue_regex, document.content)
            if target_issue not in issues:
                continue
            if keywords and not any(
                normalize_text(keyword) in normalized for keyword in keywords
            ):
                continue
            anchor_indexes.append(index)
        if not anchor_indexes:
            return ()

        title_window_size = max(
            1, min(3, int(self._spec.options.get("title_window_size", 1)))
        )
        selected_anchor_indexes = (
            anchor_indexes[-title_window_size:]
            if site.direction == Direction.BOTTOM
            else anchor_indexes[:title_window_size]
        )
        candidates: list[_ValueCandidate] = []
        for anchor_index in selected_anchor_indexes:
            anchor_document = documents[anchor_index]
            start = max(0, anchor_index - self._spec.before_documents)
            stop = min(
                len(documents),
                anchor_index + self._spec.after_documents + 1,
            )
            for document in documents[start:stop]:
                issues = self._issues(issue_regex, document.content)
                if issues and target_issue not in issues:
                    continue
                text = html_to_text(document.content)
                for value_match in value_regex.finditer(text):
                    raw_value = (
                        value_match.groupdict().get("value")
                        or value_match.group(0)
                    )
                    value = normalize_half_wave(raw_value)
                    if value is None:
                        continue
                    candidates.append(
                        _ValueCandidate(
                            value=value,
                            document=document,
                            offset=value_match.start(),
                            snippet=normalize_text(text[:240]),
                            anchor_document=anchor_document,
                        )
                    )
        if not candidates:
            return ()

        conflict_values = tuple(
            sorted({candidate.value for candidate in candidates})
        )
        return tuple(
            ParseEvidence(
                site_id=site.site_id,
                target_issue=target_issue,
                value=candidate.value,
                document_id=candidate.document.document_id,
                document_source=candidate.document.source,
                document_order=candidate.document.order,
                snippet=candidate.snippet,
                parser_name=self.name,
                parser_version=self.version,
                direction=site.direction,
                anchor_passed=True,
                keyword_passed=True,
                same_record=self._same_record(
                    candidate.document,
                    candidate.anchor_document,
                    site,
                ),
                document_relation=(
                    "same_document"
                    if candidate.document.document_id
                    == candidate.anchor_document.document_id
                    else "declared_split_document"
                ),
                record_id=candidate.document.record_id,
                expected_record_id=site.expected_record_id,
                anchors=anchors,
                keywords=keywords,
                source_offset=candidate.offset,
                candidate_count=len(candidates),
                conflict_values=conflict_values,
                boundary_issues=(target_issue,),
            )
            for candidate in candidates
        )

    @staticmethod
    def _issues(pattern: re.Pattern[str], content: str) -> set[int]:
        issues: set[int] = set()
        for match in pattern.finditer(html_to_text(content)):
            value = match.groupdict().get("issue") or match.group(0)
            digits = re.search(r"\d{1,4}", value)
            if digits:
                issues.add(int(digits.group(0)))
        return issues

    @staticmethod
    def _same_record(
        document: Document,
        anchor_document: Document,
        site: SiteSpec,
    ) -> bool:
        if site.expected_record_id is not None:
            return (
                document.record_id == site.expected_record_id
                and anchor_document.record_id == site.expected_record_id
            )
        if document.record_id is None and anchor_document.record_id is None:
            return True
        return document.record_id == anchor_document.record_id
