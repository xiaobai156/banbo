from __future__ import annotations

import re
import html
import unicodedata
from dataclasses import dataclass
from typing import Sequence

from banbo.domain.models import Document, ParseEvidence, SiteSpec
from banbo.domain.normalization import normalize_half_wave

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


class RegexLineParser:
    name = "regex_line"

    def __init__(self, spec: ParserSpec) -> None:
        self._spec = spec
        self.version = spec.parser_version
        raw_patterns = spec.options.get("patterns")
        if not isinstance(raw_patterns, (list, tuple)) or not raw_patterns:
            raise ValueError("regex_line必须配置patterns")
        self._patterns = tuple(str(pattern) for pattern in raw_patterns)

    def parse(
        self,
        site: SiteSpec,
        documents: Sequence[Document],
        target_issue: int,
    ) -> tuple[ParseEvidence, ...]:
        anchors = self._spec.anchors or site.anchors
        keywords = self._spec.keywords or site.keywords
        compact = bool(self._spec.options.get("compact", False))
        anchor_mode = str(
            self._spec.options.get("anchor_mode", site.anchor_mode)
        ).casefold()
        candidates: list[_Candidate] = []
        for document in documents:
            text = html_to_text(document.content)
            searchable = self._searchable(text, compact)
            matches = [
                self._anchor(anchor, compact) in searchable
                for anchor in anchors
            ]
            anchor_passed = (
                not anchors
                or (anchor_mode == "all" and all(matches))
                or (anchor_mode != "all" and any(matches))
            )
            if not anchor_passed:
                continue
            for raw_pattern in self._patterns:
                pattern = raw_pattern.replace(
                    "{issue}", r"(?P<_issue>\d{1,4})"
                )
                for match in re.finditer(pattern, searchable, re.IGNORECASE):
                    raw_value = match.groupdict().get("value")
                    if raw_value is None:
                        continue
                    issue_text = match.groupdict().get("_issue")
                    if issue_text is None:
                        continue
                    issue = int(issue_text)
                    value = normalize_half_wave(raw_value)
                    if value is None:
                        continue
                    candidates.append(
                        _Candidate(
                            issue=issue,
                            value=value,
                            document=document,
                            offset=match.start(),
                            snippet=searchable[
                                max(0, match.start() - 100): match.end() + 140
                            ],
                            keyword_passed=(
                                not keywords
                                or any(
                                    self._anchor(keyword, compact) in searchable
                                    for keyword in keywords
                                )
                            ),
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

    @staticmethod
    def _searchable(value: str, compact: bool) -> str:
        normalized = unicodedata.normalize("NFKC", html.unescape(value or ""))
        if compact:
            return re.sub(r"\s+", "", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def _anchor(self, value: str, compact: bool) -> str:
        return self._searchable(value, compact)
