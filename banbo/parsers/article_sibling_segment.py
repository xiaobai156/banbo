from __future__ import annotations

import re
from html import escape
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Sequence

from banbo.domain.models import Document, ParseEvidence, SiteSpec
from banbo.domain.normalization import normalize_half_wave, normalize_text
from banbo.domain import document_matches_record

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
        target_candidates: list[tuple[_Candidate, tuple[int, ...]]] = []
        for candidate_block in self._candidate_blocks(candidates):
            boundary, boundary_issues = select_directional_window(
                candidate_block,
                issue_of=lambda item: item.issue,
                direction=site.direction,
                window_size=int(self._spec.options.get("window_size", 3)),
            )
            target_candidates.extend(
                (candidate, boundary_issues)
                for candidate in boundary
                if candidate.issue == target_issue
            )
        target_candidates = tuple(target_candidates)
        if not target_candidates:
            return ()

        anchors = self._spec.anchors or site.anchors
        conflict_values = tuple(
            sorted(
                {candidate.value for candidate, _ in target_candidates}
            )
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
                linked_record_id=candidate.document.linked_record_id,
                expected_record_id=site.expected_record_id,
                anchors=anchors,
                keywords=candidate.keywords,
                source_offset=candidate.offset,
                candidate_count=len(target_candidates),
                conflict_values=conflict_values,
                boundary_issues=boundary_issues,
                parser_id=self._spec.parser_id,
                source_url=candidate.document.source_url,
                block_id=f"article:{self._parent_source(candidate.document)}",
                block_start=article[0].order,
                block_end=article[-1].order,
                document_relation=(
                    "declared_entry_script"
                    if candidate.document.record_relation
                    == "declared_entry_script"
                    else "declared_neighbor_window"
                ),
            )
            for candidate, boundary_issues in target_candidates
        )

    def _candidate_blocks(
        self,
        candidates: Sequence[_Candidate],
    ) -> tuple[tuple[_Candidate, ...], ...]:
        if not self._spec.options.get("split_on_issue_reset", False):
            return (tuple(candidates),) if candidates else ()

        blocks: list[list[_Candidate]] = [[]]
        previous_issue: int | None = None
        for candidate in candidates:
            if previous_issue is not None and candidate.issue < previous_issue:
                blocks.append([])
            blocks[-1].append(candidate)
            previous_issue = candidate.issue
        return tuple(tuple(block) for block in blocks if block)

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
        end_marker_document_span = max(
            1,
            int(self._spec.options.get("end_marker_document_span", 1)),
        )
        allow_missing_end_marker = bool(
            self._spec.options.get("allow_missing_end_marker", False)
        )
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
            end = None
            for index in range(start + 1, len(ordered)):
                marker_offset = self._marker_boundary_offset(
                    ordered[index:index + end_marker_document_span],
                    end_markers,
                )
                if marker_offset is not None:
                    end = index + marker_offset
                    break
            if end is None and allow_missing_end_marker:
                # 站点把当前期数据放在同源脚本最后一组片段里时，结束标记可能整体
                # 消失；此时只允许把归属同一脚本组的片段作为文章尾部边界。
                end = len(ordered)
            if end is not None:
                article = ordered[start:end]
                if (
                    end < len(ordered)
                    and self._spec.options.get("end_marker_keep_prefix", False)
                ):
                    # The last row and the footer can share one script fragment.
                    # Keep only text before the footer, never its following data.
                    text = html_to_text(ordered[end].content)
                    offsets = [text.find(str(marker)) for marker in end_markers]
                    offsets = [offset for offset in offsets if offset >= 0]
                    if not offsets:
                        continue
                    prefix = text[:min(offsets)]
                    if prefix.strip():
                        article += (replace(ordered[end], content=escape(prefix)),)
                matches.append(article)

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
    def _marker_boundary_offset(
        documents: Sequence[Document],
        markers: tuple[object, ...],
    ) -> int | None:
        if not markers:
            return None
        normalized_markers = tuple(
            normalize_text(str(marker)) for marker in markers
        )
        texts = tuple(
            normalize_text(html_to_text(document.content))
            for document in documents
        )
        if not all(
            any(marker in text for text in texts)
            for marker in normalized_markers
        ):
            return None
        return next(
            index
            for index, text in enumerate(texts)
            if any(marker in text for marker in normalized_markers)
        )

    @staticmethod
    def _parent_source(document: Document) -> str:
        if _DECODED_SUFFIX.search(document.source_url):
            return _DECODED_SUFFIX.sub("", document.source_url)
        return f"{document.source_url}\0{document.document_id}"
