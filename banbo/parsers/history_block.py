from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from banbo.domain.models import (
    Document,
    ParseEvidence,
    SiteSpec,
)
from banbo.domain.normalization import normalize_half_wave, normalize_text
from banbo.domain import document_matches_record

from .protocol import ParserSpec
from .boundary import document_group_key, select_directional_windows
from .text import html_to_text


@dataclass(frozen=True)
class _Candidate:
    issue: int
    value: str
    document: Document
    offset: int
    snippet: str
    anchors: tuple[str, ...]
    keywords: tuple[str, ...]

    @property
    def order(self) -> tuple[int, int]:
        return self.document.order, self.offset


class HistoryBlockParser:
    name = "history_block"

    def __init__(self, spec: ParserSpec) -> None:
        self._spec = spec
        self.version = spec.parser_version

    def parse(
        self,
        site: SiteSpec,
        documents: Sequence[Document],
        target_issue: int,
    ) -> tuple[ParseEvidence, ...]:
        issue_pattern = self._spec.issue_pattern or site.issue_pattern
        value_pattern = self._spec.value_pattern or site.value_pattern
        issue_regex = re.compile(issue_pattern, re.IGNORECASE)
        value_regex = re.compile(value_pattern, re.IGNORECASE)
        anchors = self._spec.anchors or site.anchors
        keywords = self._spec.keywords or site.keywords
        anchor_mode = str(
            self._spec.options.get("anchor_mode", site.anchor_mode)
        ).casefold()
        max_segment_chars = int(
            self._spec.options.get("max_segment_chars", 500)
        )
        skip_document_anchor = bool(
            self._spec.options.get("skip_document_anchor", False)
        )
        candidates: list[_Candidate] = []

        for document in documents:
            text = html_to_text(document.content)
            normalized_document = normalize_text(text)
            normalized_anchors = tuple(
                anchor for anchor in anchors if normalize_text(anchor) in normalized_document
            )
            anchor_passed = (
                len(normalized_anchors) == len(anchors)
                if anchor_mode == "all"
                else bool(normalized_anchors)
            )
            if anchors and not anchor_passed and not skip_document_anchor:
                continue

            issue_matches = list(issue_regex.finditer(text))
            for index, issue_match in enumerate(issue_matches):
                issue_text = issue_match.groupdict().get("issue") or issue_match.group(0)
                issue_digits = re.search(r"\d{1,4}", issue_text)
                if issue_digits is None:
                    continue
                issue = int(issue_digits.group(0))
                segment_end = (
                    issue_matches[index + 1].start()
                    if index + 1 < len(issue_matches)
                    else len(text)
                )
                segment_end = min(
                    segment_end,
                    issue_match.start() + max_segment_chars,
                )
                segment = text[issue_match.start():segment_end]
                normalized_segment = normalize_text(segment)
                matched_keywords = tuple(
                    keyword
                    for keyword in keywords
                    if normalize_text(keyword) in normalized_segment
                )
                if keywords and not matched_keywords:
                    continue
                for value_match in value_regex.finditer(segment):
                    raw_value = (
                        value_match.groupdict().get("value")
                        or value_match.group(0)
                    )
                    value = normalize_half_wave(raw_value)
                    if value is None:
                        continue
                    absolute_offset = issue_match.start() + value_match.start()
                    candidates.append(
                        _Candidate(
                            issue=issue,
                            value=value,
                            document=document,
                            offset=absolute_offset,
                            snippet=normalize_text(segment[:240]),
                            anchors=normalized_anchors,
                            keywords=matched_keywords,
                        )
                    )

        candidates.sort(key=lambda item: item.order)
        boundaries = select_directional_windows(
            candidates,
            issue_of=lambda candidate: candidate.issue,
            group_of=lambda candidate: document_group_key(candidate.document),
            direction=site.direction,
        )
        target_candidates = [
            (candidate, boundary_issues)
            for boundary, boundary_issues in boundaries
            for candidate in boundary
            if candidate.issue == target_issue
        ]
        if not target_candidates:
            return ()

        conflict_values = tuple(
            sorted({candidate.value for candidate, _ in target_candidates})
        )
        return tuple(
            ParseEvidence(
                site_id=site.site_id,
                target_issue=candidate.issue,
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
                same_record=(
                    document_matches_record(
                        candidate.document,
                        site.expected_record_id,
                    )
                ),
                record_id=candidate.document.record_id,
                expected_record_id=site.expected_record_id,
                anchors=candidate.anchors,
                keywords=candidate.keywords,
                source_offset=candidate.offset,
                candidate_count=len(target_candidates),
                conflict_values=conflict_values,
                boundary_issues=boundary_issues,
            )
            for candidate, boundary_issues in target_candidates
        )
