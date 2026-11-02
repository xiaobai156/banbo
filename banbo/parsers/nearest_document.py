from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from banbo.domain.models import Document, ParseEvidence, SiteSpec
from banbo.domain.normalization import normalize_text
from banbo.domain import documents_share_record

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
        delegate_options.update({"skip_document_anchor": True})
        delegate = HistoryBlockParser(
            replace(
                self._spec,
                strategy="history_block",
                options=delegate_options,
            )
        )
        # 先显式算出页面级方向窗口，再把它下传给每个候选文档。窗口只算一次，
        # 不再为取窗口而重复解析整页，也不会因为目标期没命中而整份消失。
        # page_window_strict 默认开：窗口外的候选直接丢弃，禁止退回单文档的
        # 退化边界（否则页面第 10 组的旧期也能通过校验）。关闭它等于放弃这道
        # 护栏，只应给「每个文档就是一份独立表」的站点用。
        page_window_strict = bool(
            self._spec.options.get("page_window_strict", True)
        )
        page_window = delegate.page_window_issues(site, tuple(documents))
        if not page_window:
            return ()
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
                    # 页面级窗口必须覆盖该候选。窗口外的目标期说明它不在页面
                    # top/bottom 前 N 组里，属于旧期，直接丢弃。关闭开关时保留
                    # 候选自身边界，等价于退回旧行为。
                    if page_window_strict and item.target_issue not in page_window:
                        continue
                    boundary = (
                        page_window if page_window_strict else item.boundary_issues
                    )
                    collected.append(
                        (
                            abs(document_index - anchor_index),
                            anchor_index,
                            replace(item, boundary_issues=boundary),
                            anchor_document,
                        )
                    )
        if not collected:
            return ()

        # 同期冲突必须上抛给统一校验裁决：把同一目标期的全部候选交给校验层，
        # 由它按 SAME_PERIOD_CONFLICT 判失败。委托的 history_block 只返回目标期
        # 证据，所以这里就是全部候选，旧实现里「最近距离」的兜底分支不可达。
        pool = [
            item for item in collected if item[2].target_issue == target_issue
        ]
        conflict_values = tuple(
            sorted({item[2].value for item in pool})
        )
        evidence: list[ParseEvidence] = []
        seen: set[tuple[str, int, str]] = set()
        for _, _, item, anchor_document in pool:
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
                    candidate_count=len(pool),
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
        return documents_share_record(
            candidate,
            anchor,
            site.expected_record_id,
        )
