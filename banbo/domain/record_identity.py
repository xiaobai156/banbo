from __future__ import annotations

import re

from .models import Document


_DECODED_SUFFIX = re.compile(r"#decoded-\d+$", re.IGNORECASE)


def _logical_source(document: Document) -> tuple[object, str]:
    return (
        document.source,
        _DECODED_SUFFIX.sub("", document.source_url),
    )


def document_matches_record(
    document: Document,
    expected_record_id: str | None,
) -> bool:
    """Return whether a document is explicitly tied to the expected record."""

    if expected_record_id is None:
        return True
    return (
        document.record_id == expected_record_id
        or document.linked_record_id == expected_record_id
    )


def documents_share_record(
    left: Document,
    right: Document,
    expected_record_id: str | None,
) -> bool:
    """Check a candidate/anchor pair without treating unrelated documents as one."""

    if expected_record_id is not None:
        return document_matches_record(
            left, expected_record_id
        ) and document_matches_record(right, expected_record_id)

    left_ids = {left.record_id, left.linked_record_id} - {None}
    right_ids = {right.record_id, right.linked_record_id} - {None}
    if left_ids or right_ids:
        return bool(left_ids & right_ids)
    return _logical_source(left) == _logical_source(right)
