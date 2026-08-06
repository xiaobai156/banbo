from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

from banbo.domain.models import Direction


CandidateT = TypeVar("CandidateT")


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
