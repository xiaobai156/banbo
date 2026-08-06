from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

from banbo.domain.models import Document, ParseEvidence, SiteSpec
from banbo.domain.normalization import normalize_half_wave, normalize_text

from .boundary import select_directional_window
from .protocol import ParserSpec
from .text import html_to_text


_DECODED_SUFFIX = re.compile(r"#decoded-\d+$", re.IGNORECASE)


@dataclass(frozen=True)
class _Candidate:
    issue: int
    value: str
    document: Document
    offset: int
    snippet: str
    keywords: tuple[str, ...]

    @property
    def order(self) -> tuple[int, int]:
        return self.document.order, self.offset


class ArticleSiblingSegmentParser:
    """Parse one article bounded inside ordered decoded script siblings."""

    name = "article_sibling_segment"

    def __init__(self, spec: ParserSpec) -> None:
        self._spec = spec
        self.version = spec.parser_version

    def parse(
        self,
        site: SiteSpec,
        documents: Sequence[Document],
        target_issue: int,
    ) -> tuple[ParseEvidence, ...]:
        article = self._find_article(site, documents)
        if article is None:
            return ()

        candidates = self._collect_candidates(site, article)
        candidates.sort(key=lambda item: item.order)
        boundary, boundary_issues = select_directional_window(
            candidates,
            issue_of=lambda candidate: candidate.issue,
            direction=site.direction,
            window_size=int(self._spec.options.get("window_size", 3)),
        )
        target_candidates = tuple(
            candidate
            for candidate in boundary
            if candidate.issue == target_issue
        )
        if not target_candidates:
            return ()

        anchors = self._spec.anchors or site.anchors
        conflict_values = tuple(
            sorted({candidate.value for candidate in target_candidates})
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
                    site.expected_record_id is None
                    or candidate.document.record_id == site.expected_record_id
                ),
                record_id=candidate.document.record_id,
                expected_record_id=site.expected_record_id,
                anchors=anchors,
                keywords=candidate.keywords,
                source_offset=candidate.offset,
                candidate_count=len(target_candidates),
                conflict_values=conflict_values,
                boundary_issues=boundary_issues,
                document_relation="declared_neighbor_window",
            )
            for candidate in target_candidates
        )

    def _find_article(
        self,
        site: SiteSpec,
        documents: Sequence[Document],
    ) -> tuple[Document, ...] | None:
        groups: dict[str, list[Document]] = defaultdict(list)
        for document in documents:
            groups[self._parent_source(document)].append(document)

        anchors = self._spec.anchors or site.anchors
        keywords = self._spec.keywords or site.keywords
        anchor_mode = str(
            self._spec.options.get("anchor_mode", site.anchor_mode)
        ).casefold()
        end_markers = tuple(self._spec.options.get("end_markers", ()))
        matches: list[tuple[Document, ...]] = []

        for siblings in groups.values():
            ordered = tuple(sorted(siblings, key=lambda item: item.order))
            start_indexes: list[int] = []
            for index, document in enumerate(ordered):
                text = normalize_text(html_to_text(document.content))
                anchor_matches = tuple(
                    normalize_text(anchor) in text for anchor in anchors
                )
                anchor_passed = (
                    not anchors
                    or (anchor_mode == "all" and all(anchor_matches))
                    or (anchor_mode != "all" and any(anchor_matches))
                )
                keyword_passed = not keywords or any(
                    normalize_text(keyword) in text for keyword in keywords
                )
                if anchor_passed and keyword_passed:
                    start_indexes.append(index)
            if not start_indexes:
                continue

            start = min(start_indexes)
            end = next(
                (
                    index
                    for index in range(start + 1, len(ordered))
                    if self._contains_all_markers(
                        ordered[index], end_markers
                    )
                ),
                None,
            )
            if end is not None:
                matches.append(ordered[start:end])

        return matches[0] if len(matches) == 1 else None

    def _collect_candidates(
        self,
        site: SiteSpec,
        documents: Sequence[Document],
    ) -> list[_Candidate]:
        issue_regex = re.compile(
            self._spec.issue_pattern or site.issue_pattern,
            re.IGNORECASE,
        )
        value_regex = re.compile(
            self._spec.value_pattern or site.value_pattern,
            re.IGNORECASE,
        )
        keywords = self._spec.keywords or site.keywords
        candidates: list[_Candidate] = []

        for document in documents:
            text = html_to_text(document.content)
            issue_matches = tuple(issue_regex.finditer(text))
            for index, issue_match in enumerate(issue_matches):
                issue_text = (
                    issue_match.groupdict().get("issue")
                    or issue_match.group(0)
                )
                issue_digits = re.search(r"\d{1,4}", issue_text)
                if issue_digits is None:
                    continue
                segment_end = (
                    issue_matches[index + 1].start()
                    if index + 1 < len(issue_matches)
                    else len(text)
                )
                segment = text[issue_match.start():segment_end]
                keyword_matches = tuple(
                    (keyword, match)
                    for keyword in keywords
                    for match in re.finditer(
                        re.escape(keyword), segment, re.IGNORECASE
                    )
                )
                if keywords and not keyword_matches:
                    continue
                keyword_end = 0
                matched_keywords: tuple[str, ...] = ()
                if keyword_matches:
                    first_keyword_start = min(
                        match.start() for _, match in keyword_matches
                    )
                    at_first = tuple(
                        (keyword, match)
                        for keyword, match in keyword_matches
                        if match.start() == first_keyword_start
                    )
                    keyword_end = max(match.end() for _, match in at_first)
                    matched_keywords = tuple(
                        dict.fromkeys(keyword for keyword, _ in at_first)
                    )
                for value_match in value_regex.finditer(segment, keyword_end):
                    raw_value = (
                        value_match.groupdict().get("value")
                        or value_match.group(0)
                    )
                    value = normalize_half_wave(raw_value)
                    if value is None:
                        continue
                    candidates.append(
                        _Candidate(
                            issue=int(issue_digits.group(0)),
                            value=value,
                            document=document,
                            offset=(
                                issue_match.start() + value_match.start()
                            ),
                            snippet=normalize_text(segment[:240]),
                            keywords=matched_keywords,
                        )
                    )
        return candidates

    @staticmethod
    def _contains_all_markers(
        document: Document,
        markers: tuple[object, ...],
    ) -> bool:
        if not markers:
            return False
        text = normalize_text(html_to_text(document.content))
        return all(normalize_text(str(marker)) in text for marker in markers)

    @staticmethod
    def _parent_source(document: Document) -> str:
        if _DECODED_SUFFIX.search(document.source_url):
            return _DECODED_SUFFIX.sub("", document.source_url)
        return f"{document.source_url}\0{document.document_id}"
