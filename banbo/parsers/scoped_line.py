from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from banbo.domain.models import Document, ParseEvidence, SiteSpec
from banbo.domain.normalization import normalize_half_wave, normalize_text

from .protocol import ParserSpec
from .boundary import select_directional_window
from .text import html_to_text


@dataclass(frozen=True)
class _Candidate:
    issue: int
    value: str
    document: Document
    offset: int
    snippet: str
    keyword_passed: bool


class ScopedLineParser:
    name = "scoped_line"

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
        value_regex = re.compile(
            self._spec.value_pattern or site.value_pattern,
            re.IGNORECASE,
        )
        marker = str(self._spec.options.get("marker", ""))
        candidates: list[_Candidate] = []
        any_issue_regex = re.compile(r"(?:第)?\s*\d{1,4}\s*期")
        for document in documents:
            text = html_to_text(document.content)
            normalized_document = normalize_text(text)
            if anchors and not all(
                normalize_text(anchor) in normalized_document
                for anchor in anchors
            ):
                continue
            issue_matches = list(any_issue_regex.finditer(text))
            for index, issue_match in enumerate(issue_matches):
                digits = re.search(r"\d{1,4}", issue_match.group(0))
                if digits is None:
                    continue
                issue = int(digits.group(0))
                end = (
                    issue_matches[index + 1].start()
                    if index + 1 < len(issue_matches)
                    else min(len(text), issue_match.start() + 800)
                )
                segment = text[issue_match.start():end]
                normalized_segment = normalize_text(segment)
                keyword_found = any(
                    normalize_text(keyword) in normalized_segment
                    for keyword in keywords
                )
                marker_found = bool(
                    marker
                    and normalize_text(marker) in normalized_segment
                )
                if keywords and not keyword_found and not marker_found:
                    continue
                value_zone = segment
                if marker:
                    marker_index = normalize_text(segment).find(
                        normalize_text(marker)
                    )
                    if marker_index < 0:
                        continue
                    value_zone = normalize_text(segment)[marker_index:]
                for value_match in value_regex.finditer(value_zone):
                    raw_value = (
                        value_match.groupdict().get("value")
                        or value_match.group(0)
                    )
                    value = normalize_half_wave(raw_value)
                    if value is None:
                        continue
                    candidates.append(
                        _Candidate(
                            issue=issue,
                            value=value,
                            document=document,
                            offset=issue_match.start() + value_match.start(),
                            snippet=normalized_segment[:240],
                            keyword_passed=True,
                        )
                    )
        candidates.sort(key=lambda item: (item.document.order, item.offset))
        if not candidates:
            return ()
        boundary, boundary_issues = select_directional_window(
            candidates,
            issue_of=lambda candidate: candidate.issue,
            direction=site.direction,
        )
        target_candidates = tuple(
            candidate for candidate in boundary if candidate.issue == target_issue
        )
        if not target_candidates:
            return ()
        conflict_values = tuple(sorted({item.value for item in target_candidates}))
        return tuple(
            ParseEvidence(
                site_id=site.site_id,
                target_issue=item.issue,
                value=item.value,
                document_id=item.document.document_id,
                document_source=item.document.source,
                document_order=item.document.order,
                snippet=item.snippet,
                parser_name=self.name,
                parser_version=self.version,
                direction=site.direction,
                anchor_passed=True,
                keyword_passed=item.keyword_passed,
                same_record=(
                    site.expected_record_id is None
                    or item.document.record_id == site.expected_record_id
                ),
                record_id=item.document.record_id,
                expected_record_id=site.expected_record_id,
                anchors=anchors,
                keywords=keywords,
                source_offset=item.offset,
                candidate_count=len(target_candidates),
                conflict_values=conflict_values,
                boundary_issues=boundary_issues,
            )
            for item in target_candidates
        )
