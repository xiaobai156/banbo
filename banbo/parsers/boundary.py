from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Hashable, TypeVar

from banbo.domain.models import Direction, Document


CandidateT = TypeVar("CandidateT")
_DECODED_SUFFIX = re.compile(r"#decoded-\d+$", re.IGNORECASE)
_ANCHOR_SEGMENT_SUFFIX = re.compile(r"#anchor-segment-\d+$", re.IGNORECASE)


def document_group_key(document: Document) -> tuple[object, ...]:
    """Keep direction windows inside one fetched source document.

    Decoded fragments from one script are logical siblings and therefore share
    a window.  Page, iframe, inline-script, API, and unrelated script documents
    remain isolated even when discovery happened to return them consecutively.
    """

    source_url = _ANCHOR_SEGMENT_SUFFIX.sub("", document.source_url)
    source_url = _DECODED_SUFFIX.sub("", source_url)
    return (
        document.source,
        source_url,
        document.record_id,
        document.linked_record_id,
    )


def select_directional_window(
    candidates: Sequence[CandidateT],
    *,
    issue_of: Callable[[CandidateT], int],
    direction: Direction,
    window_size: int = 3,
) -> tuple[tuple[CandidateT, ...], tuple[int, ...]]:
    if window_size != 3:
        raise ValueError("半波方向窗口必须固定为3组")
    groups: list[list[CandidateT]] = []
    group_issues: list[int] = []
    for candidate in candidates:
        issue = issue_of(candidate)
        if not groups or group_issues[-1] != issue:
            groups.append([])
            group_issues.append(issue)
        groups[-1].append(candidate)
    selected_groups = (
        groups[-window_size:]
        if direction == Direction.BOTTOM
        else groups[:window_size]
    )
    selected_issues = (
        group_issues[-window_size:]
        if direction == Direction.BOTTOM
        else group_issues[:window_size]
    )
    return (
        tuple(candidate for group in selected_groups for candidate in group),
        tuple(selected_issues),
    )


def select_directional_windows(
    candidates: Sequence[CandidateT],
    *,
    issue_of: Callable[[CandidateT], int],
    group_of: Callable[[CandidateT], Hashable],
    direction: Direction,
    window_size: int = 3,
) -> tuple[tuple[tuple[CandidateT, ...], tuple[int, ...]], ...]:
    grouped: dict[Hashable, list[CandidateT]] = {}
    for candidate in candidates:
        grouped.setdefault(group_of(candidate), []).append(candidate)
    return tuple(
        select_directional_window(
            group,
            issue_of=issue_of,
            direction=direction,
            window_size=window_size,
        )
        for group in grouped.values()
    )
