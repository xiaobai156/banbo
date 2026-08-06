from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from banbo.domain.normalization import normalize_text


class RecordBoundaryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecordBoundarySpec:
    record_id: str
    id_keys: tuple[str, ...] = ("id", "record_id", "article_id", "topic_id")
    expected_author: str | None = None
    expected_title_contains: tuple[str, ...] = ()
    expected_column: str | None = None
    author_keys: tuple[str, ...] = ("author", "author_name", "username", "user_name")
    title_keys: tuple[str, ...] = ("title", "topic", "sub_topic", "name")
    column_keys: tuple[str, ...] = ("column", "category", "channel", "section")


@dataclass(frozen=True)
class ResolvedRecord:
    path: tuple[str | int, ...]
    record: dict[str, Any]


_PATH_RECORD_PATTERNS = (
    re.compile(r"/article/(?:admin|manager)/([^/?#]+?)(?:\.html)?/?$", re.I),
    re.compile(r"/users/[^/]+/references/([^/?#]+?)(?:\.html)?/?$", re.I),
    re.compile(r"/topic/([^/?#]+?)(?:\.html)?/?$", re.I),
)


def extract_record_id(url: str, pattern: str | None = None) -> str | None:
    parsed = urlparse(url)
    if pattern:
        match = re.search(pattern, url)
        if not match:
            return None
        for value in match.groupdict().values():
            if value is not None:
                return str(value)
        if match.lastindex:
            return str(match.group(1))
        return None
    for compiled in _PATH_RECORD_PATTERNS:
        match = compiled.search(parsed.path)
        if match:
            return match.group(1)
    query = parse_qs(parsed.query, keep_blank_values=False)
    for key in ("id", "record_id", "article_id", "topic_id"):
        values = query.get(key)
        if values:
            return str(values[0])
    return None


def _walk(
    value: object,
    path: tuple[str | int, ...] = (),
):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _walk(child, path + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, path + (index,))


def _first_text(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = record.get(key)
        if value is not None and normalize_text(str(value)):
            return normalize_text(str(value))
    return ""


def resolve_unique_record(
    payload: object,
    spec: RecordBoundarySpec,
) -> ResolvedRecord:
    expected_id = str(spec.record_id)
    matches: list[ResolvedRecord] = []
    for path, record in _walk(payload):
        if any(
            key in record and str(record.get(key)) == expected_id
            for key in spec.id_keys
        ):
            matches.append(ResolvedRecord(path=path, record=record))

    if not matches:
        raise RecordBoundaryError(f"未找到URL记录ID：{expected_id}")
    if len(matches) > 1:
        raise RecordBoundaryError(f"发现多个同ID记录：{expected_id}")

    resolved = matches[0]
    if spec.expected_author is not None:
        actual_author = _first_text(resolved.record, spec.author_keys)
        if actual_author != normalize_text(spec.expected_author):
            raise RecordBoundaryError(
                f"作者校验失败：期望{spec.expected_author}，实际{actual_author or '空'}"
            )

    if spec.expected_title_contains:
        actual_title = _first_text(resolved.record, spec.title_keys)
        if not all(
            normalize_text(anchor) in actual_title
            for anchor in spec.expected_title_contains
        ):
            raise RecordBoundaryError(
                f"标题校验失败：{actual_title or '空'}"
            )

    if spec.expected_column is not None:
        actual_column = _first_text(resolved.record, spec.column_keys)
        if actual_column != normalize_text(spec.expected_column):
            raise RecordBoundaryError(
                f"栏目校验失败：期望{spec.expected_column}，实际{actual_column or '空'}"
            )

    return resolved
