from __future__ import annotations

import re

from banbo.domain.models import Direction

from .protocol import ParserSpec


class ParserSpecError(ValueError):
    pass


def _string_tuple(item: dict, key: str, index: int) -> tuple[str, ...]:
    value = item.get(key)
    if not isinstance(value, list) or not value:
        raise ParserSpecError(f"specs[{index}].{key} 必须是非空数组")
    result = tuple(str(part).strip() for part in value)
    if any(not part for part in result):
        raise ParserSpecError(f"specs[{index}].{key} 不能包含空值")
    return result


def _non_negative_int(item: dict, key: str, index: int) -> int:
    value = item.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ParserSpecError(f"specs[{index}].{key} 必须是非负整数")
    return value


def parse_parser_specs(payload: object) -> tuple[ParserSpec, ...]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ParserSpecError("parser_specs schema_version 必须为1")
    raw_specs = payload.get("specs")
    if not isinstance(raw_specs, list):
        raise ParserSpecError("parser_specs.specs 必须是数组")
    raw_entry_script_links = payload.get("entry_script_links", [])
    if not isinstance(raw_entry_script_links, list):
        raise ParserSpecError("parser_specs.entry_script_links 必须是数组")
    entry_script_links = tuple(
        str(site_id).strip() for site_id in raw_entry_script_links
    )
    if any(not site_id for site_id in entry_script_links):
        raise ParserSpecError(
            "parser_specs.entry_script_links 不能包含空值"
        )
    if len(entry_script_links) != len(set(entry_script_links)):
        raise ParserSpecError(
            "parser_specs.entry_script_links 不能包含重复站点"
        )

    specs: list[ParserSpec] = []
    seen_site_ids: set[str] = set()
    seen_parser_ids: set[str] = set()
    for index, item in enumerate(raw_specs):
        if not isinstance(item, dict):
            raise ParserSpecError(f"specs[{index}] 必须是对象")
        site_id = str(item.get("site_id", "")).strip()
        parser_id = str(item.get("parser_id", "")).strip()
        strategy = str(item.get("strategy", "")).strip()
        parser_version = str(item.get("parser_version", "")).strip()
        if not site_id or not parser_id or not strategy or not parser_version:
            raise ParserSpecError(
                f"specs[{index}] 缺少site_id、parser_id、strategy或parser_version"
            )
        if site_id in seen_site_ids:
            raise ParserSpecError(f"site_id重复：{site_id}")
        seen_site_ids.add(site_id)
        if parser_id in seen_parser_ids:
            raise ParserSpecError(f"parser_id重复：{parser_id}")
        seen_parser_ids.add(parser_id)
        try:
            direction = Direction(str(item.get("direction", "")))
        except ValueError as exc:
            raise ParserSpecError(
                f"specs[{index}].direction 必须是top或bottom"
            ) from exc

        issue_pattern = str(item.get("issue_pattern", "")).strip()
        value_pattern = str(item.get("value_pattern", "")).strip()
        for key, pattern in (
            ("issue_pattern", issue_pattern),
            ("value_pattern", value_pattern),
        ):
            if not pattern:
                raise ParserSpecError(f"specs[{index}].{key} 不能为空")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ParserSpecError(
                    f"specs[{index}].{key} 正则无效：{exc}"
                ) from exc

        for key in ("record_id_pattern", "topic_id_pattern"):
            raw_pattern = item.get(key)
            if raw_pattern is None:
                continue
            pattern = str(raw_pattern).strip()
            if not pattern:
                raise ParserSpecError(f"specs[{index}].{key} 不能为空")
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise ParserSpecError(
                    f"specs[{index}].{key} 正则无效：{exc}"
                ) from exc
            if compiled.groups < 1:
                raise ParserSpecError(
                    f"specs[{index}].{key} 必须包含记录ID捕获组"
                )

        target_only = item.get("target_only")
        if not isinstance(target_only, bool):
            raise ParserSpecError(
                f"specs[{index}].target_only 必须是布尔值"
            )
        options = item.get("options")
        if not isinstance(options, dict):
            raise ParserSpecError(f"specs[{index}].options 必须是对象")
        if options.get("target_only_scope") is True:
            raise ParserSpecError(
                f"specs[{index}].options.target_only_scope 禁止绕过方向窗口"
            )
        if "window_size" in options and options["window_size"] != 3:
            raise ParserSpecError(
                f"specs[{index}].options.window_size 必须固定为3"
            )
        max_response_bytes = options.get("max_response_bytes")
        if (
            max_response_bytes is not None
            and (
                not isinstance(max_response_bytes, int)
                or isinstance(max_response_bytes, bool)
                or max_response_bytes <= 0
            )
        ):
            raise ParserSpecError(
                f"specs[{index}].options.max_response_bytes 必须是正整数"
            )
        additional_requests = options.get("additional_requests")
        if additional_requests is not None:
            if (
                not isinstance(additional_requests, list)
                or not additional_requests
            ):
                raise ParserSpecError(
                    f"specs[{index}].options.additional_requests 必须是非空数组"
                )
            for position, entry in enumerate(additional_requests):
                if not isinstance(entry, dict):
                    raise ParserSpecError(
                        f"specs[{index}].options.additional_requests[{position}]"
                        " 必须是对象"
                    )
                source = str(entry.get("source", "")).strip().lower()
                url = str(entry.get("url", "")).strip()
                if source not in {"script", "iframe", "api"}:
                    raise ParserSpecError(
                        f"specs[{index}].options.additional_requests[{position}]"
                        ".source 必须是script、iframe或api"
                    )
                if not url:
                    raise ParserSpecError(
                        f"specs[{index}].options.additional_requests[{position}]"
                        ".url 不能为空"
                    )
        if strategy == "article_sibling_segment":
            end_markers = options.get("end_markers")
            if (
                not isinstance(end_markers, list)
                or not end_markers
                or any(
                    not isinstance(marker, str) or not marker.strip()
                    for marker in end_markers
                )
            ):
                raise ParserSpecError(
                    f"specs[{index}].options.end_markers 必须是非空字符串数组"
                )
        if strategy == "regex_line":
            patterns = options.get("patterns")
            if not isinstance(patterns, list) or not patterns:
                raise ParserSpecError(
                    f"specs[{index}].options.patterns 必须是非空数组"
                )
            if any(str(pattern).count("{issue}") != 1 for pattern in patterns):
                raise ParserSpecError(
                    f"specs[{index}].options.patterns 必须恰好包含一个{{issue}}"
                )
        if strategy == "dynamic_api" and "source" not in options:
            raise ParserSpecError(
                f"specs[{index}].options.source 必须是动态来源对象"
            )
        if "source" in options:
            source = options.get("source")
            if not isinstance(source, dict):
                raise ParserSpecError(
                    f"specs[{index}].options.source 必须是来源对象"
                )
            kind = str(source.get("kind", "")).strip()
            if kind == "article_list":
                for key in ("title_anchor", "title_suffix", "next_text"):
                    if not isinstance(source.get(key), str) or not source[key].strip():
                        raise ParserSpecError(
                            f"specs[{index}].options.source.{key} 不能为空"
                        )
                max_pages = source.get("max_pages")
                if (
                    not isinstance(max_pages, int)
                    or isinstance(max_pages, bool)
                    or not 1 <= max_pages <= 9
                ):
                    raise ParserSpecError(
                        f"specs[{index}].options.source.max_pages 必须是1到9的整数"
                    )
            elif strategy == "dynamic_api":
                user_id = str(source.get("user_id", "")).strip()
                topic = str(source.get("topic", "")).strip()
                if kind not in {"forums", "references"}:
                    raise ParserSpecError(
                        f"specs[{index}].options.source.kind 无效"
                    )
                if not user_id or not topic:
                    raise ParserSpecError(
                        f"specs[{index}].options.source 缺少user_id或topic"
                    )
            else:
                raise ParserSpecError(
                    f"specs[{index}].options.source.kind 无效"
                )

        specs.append(
            ParserSpec(
                site_id=site_id,
                strategy=strategy,
                parser_version=parser_version,
                parser_id=parser_id,
                direction=direction,
                anchors=_string_tuple(item, "anchors", index),
                keywords=_string_tuple(item, "keywords", index),
                issue_pattern=issue_pattern,
                value_pattern=value_pattern,
                before_documents=_non_negative_int(
                    item, "before_documents", index
                ),
                after_documents=_non_negative_int(
                    item, "after_documents", index
                ),
                target_only=target_only,
                record_id_pattern=(
                    None
                    if item.get("record_id_pattern") is None
                    else str(item["record_id_pattern"])
                ),
                topic_id_pattern=(
                    None
                    if item.get("topic_id_pattern") is None
                    else str(item["topic_id_pattern"])
                ),
                options=dict(options),
                link_external_scripts_to_entry=(
                    site_id in entry_script_links
                ),
            )
        )
    unknown_entry_links = sorted(
        set(entry_script_links) - seen_site_ids
    )
    if unknown_entry_links:
        raise ParserSpecError(
            "entry_script_links包含未知站点："
            + ",".join(unknown_entry_links)
        )
    return tuple(specs)
