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

# 生肖字集合：用于判断片段标记前后是否构成「期号 + 生肖」的同一表格行。
_ZODIAC = "鼠牛虎兔龙蛇马羊猴鸡狗猪"
# 只允许「期号 + 单个生肖字」这种形态参与跨片段拼接，中间夹别的文字不算。
_ZODIAC_ROW_HEAD = re.compile(r"^\d{1,4}\s*期\s*[鼠牛虎兔龙蛇马羊猴鸡狗猪]$")


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

    def _collect_candidates(
        self,
        site: SiteSpec,
        documents: Sequence[Document],
    ) -> list[_Candidate]:
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
        # 表格类站点：字段名只出现在表头，切出来的单期片段里没有关键字，
        # 由上层锚点（如表格唯一列头）保证栏目正确，这里可关闭逐段关键字检查。
        skip_keyword_check = bool(
            self._spec.options.get("skip_keyword_check", False)
        )
        # 默认片段标记是硬边界。仅表格类站点显式开启时，才允许在「期号+生肖」
        # 的同一行被片段拆开处拼接（汉锺离）。默认关，避免全局放宽。
        join_zodiac_fragment = bool(
            self._spec.options.get("join_zodiac_fragment", False)
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
                # 片段标记是硬边界：combined_sibling 用 \u2063 拼接多个解码片段，
                # 切段越过它会把下一片段里属于别的期的值算到本期头上。
                # 只有站点显式开启 join_zodiac_fragment 时才允许在「同一表格行
                # 被拆开」处拼接：汉锺离的表格是「299期 猴 ␣ 蓝双」，期号后只有
                # 一个生肖字，然后断点，然后半波值——这才是同一行被拆开。
                # 期号与断点之间夹了别的文字（如「296期 绝杀半波 ␣ 绿双」）一律截断。
                search_from = issue_match.start()
                while True:
                    marker = text.find("\u2063", search_from, segment_end)
                    if marker == -1:
                        break
                    if not join_zodiac_fragment:
                        segment_end = marker
                        break
                    before = text[issue_match.start():marker].rstrip()
                    following = text[marker + 1: segment_end].lstrip()
                    if (
                        _ZODIAC_ROW_HEAD.match(before)
                        and not issue_regex.match(following)
                        and value_regex.match(following)
                    ):
                        search_from = marker + 1
                        continue
                    segment_end = marker
                    break
                segment = text[issue_match.start():segment_end]
                normalized_segment = normalize_text(segment)
                matched_keywords = tuple(
                    keyword
                    for keyword in keywords
                    if normalize_text(keyword) in normalized_segment
                )
                if keywords and not skip_keyword_check and not matched_keywords:
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
        return candidates

    def page_window_issues(
        self,
        site: SiteSpec,
        documents: Sequence[Document],
    ) -> tuple[int, ...]:
        """只算页面级方向窗口，不按目标期过滤。

        上层（nearest_document）需要显式拿到窗口再下传：既省掉为取窗口而
        重复解析整页，也避免窗口因为目标期没命中而整份消失。
        """

        candidates = self._collect_candidates(site, documents)
        if not candidates:
            return ()
        windows = select_directional_windows(
            candidates,
            issue_of=lambda candidate: candidate.issue,
            group_of=lambda candidate: document_group_key(candidate.document),
            direction=site.direction,
        )
        for _, issues in windows:
            return issues
        return ()

    def parse(
        self,
        site: SiteSpec,
        documents: Sequence[Document],
        target_issue: int,
    ) -> tuple[ParseEvidence, ...]:
        candidates = self._collect_candidates(site, documents)
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
