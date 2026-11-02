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
    """Select a direction window per document group.

    A group whose own issue sequence is shorter than ``window_size`` cannot
    prove that the target period really sits in the page-level top/bottom
    window: for sites that publish one script per period every group holds a
    single issue, so a per-group window would degenerate to that one issue and
    let any period through (cross-period borrowing).  For those degenerate
    groups the page-level window is used instead, so the target must still be
    among the first/last ``window_size`` distinct issues of the whole page.
    """

    if window_size != 3:
        raise ValueError("半波方向窗口必须固定为3组")
    grouped: dict[Hashable, list[CandidateT]] = {}
    for candidate in candidates:
        grouped.setdefault(group_of(candidate), []).append(candidate)

    global_issues: list[int] = []
    for candidate in candidates:
        issue = issue_of(candidate)
        if not global_issues or global_issues[-1] != issue:
            global_issues.append(issue)
    global_window = tuple(
        global_issues[-window_size:]
        if direction == Direction.BOTTOM
        else global_issues[:window_size]
    )

    # 所有组一律按页面级窗口裁剪。旧实现只对「不足 3 组」的组回退到全局窗口，
    # 组内已有 3 期以上时仍用本组窗口，于是页面前三组在 page 里、第 4~6 组在
    # 另一个脚本里时，本组窗口会整体平移到第 4~6 组，目标期跟着「合法」通过。
    # 组内窗口仍然算出来，只用于确认该组本身覆盖了全局窗口。
    windows: list[tuple[tuple[CandidateT, ...], tuple[int, ...]]] = []
    if not global_window:
        return ()
    allowed = set(global_window)
    for group in grouped.values():
        scoped = tuple(
            candidate for candidate in group if issue_of(candidate) in allowed
        )
        if scoped:
            windows.append((scoped, global_window))
    return tuple(windows)
