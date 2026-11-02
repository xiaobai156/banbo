from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import replace
from typing import Sequence

from banbo.domain.models import Document, ParseEvidence, SiteSpec
from banbo.domain import documents_share_record
from .history_block import HistoryBlockParser
from .protocol import ParserSpec
from .regex_line import RegexLineParser
from .text import html_to_text


_DECODED_SUFFIX = re.compile(r"#decoded-\d+$", re.IGNORECASE)


class CombinedSiblingParser:
    """Parse rows split across sibling decoded fragments."""

    name = "combined_sibling"

    def __init__(self, spec: ParserSpec) -> None:
        self._spec = spec
        self.version = spec.parser_version

    def parse(
        self,
        site: SiteSpec,
        documents: Sequence[Document],
        target_issue: int,
    ) -> tuple[ParseEvidence, ...]:
        groups: dict[str, list[Document]] = defaultdict(list)
        for document in documents:
            groups[self._parent_source(document)].append(document)

        anchors = self._spec.anchors or site.anchors
        anchor_mode = str(
            self._spec.options.get("anchor_mode", site.anchor_mode)
        ).casefold()
        anchor_same_document = bool(
            self._spec.options.get("anchor_same_document", False)
        )
        compact = bool(self._spec.options.get("compact", False))
        delegate = self._delegate()
        delegate_site = replace(
            site,
            anchors=(),
            keywords=(
                ()
                if self._spec.options.get("skip_keyword_check", False)
                else site.keywords
            ),
        )
        evidence: list[ParseEvidence] = []
        seen: set[tuple[str, int, str]] = set()

        for siblings in groups.values():
            ordered = tuple(sorted(siblings, key=lambda item: item.order))
            combined, ranges = self._combine(ordered, compact)
            delegate_content, delegate_offsets = self._delegate_content(
                combined, compact
            )
            normalized_anchors = tuple(
                self._searchable(anchor, compact) for anchor in anchors
            )
            searchable_combined = self._searchable(combined, compact)
            matches = [anchor in searchable_combined for anchor in normalized_anchors]
            if anchor_same_document and anchors:
                anchor_passed = any(
                    self._document_has_anchor(
                        document,
                        normalized_anchors,
                        anchor_mode,
                        compact,
                    )
                    for document in ordered
                )
            else:
                anchor_passed = (
                    not anchors
                    or (anchor_mode == "all" and all(matches))
                    or (anchor_mode != "all" and any(matches))
                )
            if not anchor_passed:
                continue

            synthetic = replace(
                ordered[0],
                document_id=f"{ordered[0].document_id}:combined",
                content=delegate_content,
            )
            for item in delegate.parse(
                delegate_site,
                (synthetic,),
                target_issue,
            ):
                combined_offset = self._to_combined_offset(
                    item.source_offset, delegate_offsets
                )
                if combined_offset is None:
                    continue
                mapped = self._map_offset(combined_offset, ranges)
                if mapped is None:
                    continue
                candidate, local_offset = mapped
                key = (candidate.document_id, local_offset, item.value)
                if key in seen:
                    continue
                seen.add(key)
                anchor_documents = tuple(
                    document
                    for document in ordered
                    if self._document_has_anchor(
                        document,
                        anchors,
                        "any",
                        compact,
                    )
                )
                same_document = self._document_has_anchor(
                    candidate,
                    anchors,
                    anchor_mode,
                    compact,
                )
                evidence.append(
                    replace(
                        item,
                        document_id=candidate.document_id,
                        document_source=candidate.source,
                        document_order=candidate.order,
                        source_offset=local_offset,
                        parser_name=self.name,
                        parser_version=self.version,
                        anchor_passed=True,
                        same_record=any(
                            self._same_record(candidate, anchor, site)
                            for anchor in anchor_documents
                        ),
                        record_id=candidate.record_id,
                        expected_record_id=site.expected_record_id,
                        source_url=candidate.source_url,
                        document_relation=(
                            "same_document"
                            if same_document
                            else "declared_neighbor_window"
                        ),
                        anchors=anchors,
                    )
                )
        return tuple(evidence)

    def _delegate(self):
        skip_keywords = bool(
            self._spec.options.get("skip_keyword_check", False)
        )
        if self._spec.options.get("patterns"):
            return RegexLineParser(
                replace(
                    self._spec,
                    strategy="regex_line",
                    anchors=(),
                    keywords=() if skip_keywords else self._spec.keywords,
                )
            )
        return HistoryBlockParser(
            replace(
                self._spec,
                strategy="history_block",
                anchors=(),
                keywords=() if skip_keywords else self._spec.keywords,
                options={
                    **self._spec.options,
                    "skip_document_anchor": True,
                },
            )
        )

    @staticmethod
    def _combine(
        documents: Sequence[Document],
        compact: bool,
    ) -> tuple[str, tuple[tuple[int, int, Document], ...]]:
        parts: list[str] = []
        ranges: list[tuple[int, int, Document]] = []
        offset = 0
        for index, document in enumerate(documents):
            if index:
                # Keep compact fragments non-adjacent so a trailing digit in
                # one decoded fragment cannot fuse with the next fragment's
                # period (for example ``开兔04`` + ``213期`` -> ``4213期``).
                separator = "\u2063" if compact else " "
                parts.append(separator)
                offset += len(separator)
            part = CombinedSiblingParser._searchable(
                html_to_text(document.content), compact
            )
            start = offset
            parts.append(part)
            offset += len(part)
            ranges.append((start, offset, document))
        return "".join(parts), tuple(ranges)

    @staticmethod
    def _delegate_content(
        combined: str,
        compact: bool,
    ) -> tuple[str, tuple[int, ...]]:
        """Keep fragment markers except where a history row legitimately spans them.

        Markers used to be stripped between any two text tokens so that
        ``马`` + ``蓝单`` read as one history row.  That also erased the boundary
        between a period and the next fragment's value, so slicing the current
        period's segment swallowed the following fragment's value — a real
        cross-period borrow (hw-0105: ``296期`` took ``绿双`` from the next
        fragment).  The marker is now dropped only when the following fragment
        continues the same row, i.e. it does not itself start a new period and
        the preceding fragment did not already end a value.  A marker that
        separates a period from a value on either side is preserved so the
        segment builder stops there.
        """

        if not compact:
            return combined, tuple(range(len(combined)))
        marker = "\u2063"
        period_pattern = re.compile(r"\d{1,4}\s*期")
        value_pattern = re.compile(r"[红绿蓝]\s*(?:波\s*)?[单双]")
        output: list[str] = []
        offsets: list[int] = []
        for index, char in enumerate(combined):
            if char != marker:
                output.append(char)
                offsets.append(index)
                continue
            previous = combined[index - 1] if index else ""
            following = combined[index + 1] if index + 1 < len(combined) else ""
            # 数字夹数字：保护 ``开兔04`` + ``213期`` 这类相邻数字被粘成一个期号。
            if previous.isdigit() and following.isdigit():
                output.append(char)
                offsets.append(index)
                continue
            head = combined[max(0, index - 40): index]
            tail = combined[index + 1: index + 41]
            # 片段前面已经有值、后面又开始新的一期：属于两期之间的边界，保留。
            if value_pattern.search(head) and period_pattern.search(tail):
                output.append(char)
                offsets.append(index)
                continue
            # 片段后面紧跟一个新期号：保留边界，避免把下一期算进本期。
            if period_pattern.match(tail.lstrip()):
                output.append(char)
                offsets.append(index)
                continue
            # 片段前面还没有值、后面却以值开头：本期会把下一片段的值吃掉，保留边界。
            if not value_pattern.search(head) and value_pattern.match(tail.lstrip()):
                output.append(char)
                offsets.append(index)
                continue
            continue
        return "".join(output), tuple(offsets)

    @staticmethod
    def _to_combined_offset(
        offset: int,
        delegate_offsets: Sequence[int],
    ) -> int | None:
        if not delegate_offsets:
            return offset
        if 0 <= offset < len(delegate_offsets):
            return delegate_offsets[offset]
        # 越界偏移不能回退到最后一个片段的末尾：那会把上一个片段的期号
        # 和下一个片段的值拼成同一行（例如 296期 + 绿双 被算成 296=绿双），
        # 属于跨片段/跨期借值。返回 None 让调用方丢弃该候选。
        return None

    @staticmethod
    def _map_offset(
        offset: int,
        ranges: Sequence[tuple[int, int, Document]],
    ) -> tuple[Document, int] | None:
        for start, end, document in ranges:
            if start <= offset < end:
                return document, offset - start
        return None

    @staticmethod
    def _searchable(value: str, compact: bool) -> str:
        normalized = unicodedata.normalize("NFKC", value or "")
        if compact:
            return re.sub(r"\s+", "", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    @classmethod
    def _document_has_anchor(
        cls,
        document: Document,
        anchors: tuple[str, ...],
        anchor_mode: str,
        compact: bool,
    ) -> bool:
        if not anchors:
            return True
        text = cls._searchable(html_to_text(document.content), compact)
        matches = [cls._searchable(anchor, compact) in text for anchor in anchors]
        return all(matches) if anchor_mode == "all" else any(matches)

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

    @staticmethod
    def _parent_source(document: Document) -> str:
        source_url = document.source_url
        if _DECODED_SUFFIX.search(source_url):
            return _DECODED_SUFFIX.sub("", source_url)
        return f"{source_url}\0{document.document_id}"
