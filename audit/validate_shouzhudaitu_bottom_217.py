from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass

from banbo.application.single_period import default_document_provider
from banbo.cli import _load_runtime
from banbo.domain.models import Direction, Document
from banbo.domain.normalization import normalize_half_wave, normalize_text
from banbo.fetch.dynamic_records import extract_record_id
from banbo.parsers.boundary import select_directional_window
from banbo.parsers.text import html_to_text


SITE_ID = "hw-0141"
ARTICLE_ISSUE = 217
VALIDATION_ISSUES = (217, 216, 215, 214, 999)
_DECODED_SUFFIX = re.compile(r"#decoded-\d+$", re.IGNORECASE)


@dataclass(frozen=True)
class Candidate:
    issue: int
    value: str
    document: Document
    offset: int
    snippet: str


def _parent_source(document: Document) -> str:
    if _DECODED_SUFFIX.search(document.source_url):
        return _DECODED_SUFFIX.sub("", document.source_url)
    return f"{document.source_url}\0{document.document_id}"


def _article_documents(documents, site, spec):
    groups: dict[str, list[Document]] = defaultdict(list)
    for document in documents:
        groups[_parent_source(document)].append(document)

    matches = []
    for parent_source, siblings in groups.items():
        ordered = tuple(sorted(siblings, key=lambda item: item.order))
        anchor_indexes = []
        for index, document in enumerate(ordered):
            text = normalize_text(html_to_text(document.content))
            if (
                site.name in text
                and f"{ARTICLE_ISSUE}期" in text
                and any(keyword in text for keyword in spec.keywords)
            ):
                anchor_indexes.append(index)
        if not anchor_indexes:
            continue
        start = min(anchor_indexes)
        end = None
        for index in range(start + 1, len(ordered)):
            text = normalize_text(html_to_text(ordered[index].content))
            if (
                "context_switch" in ordered[index].content
                or ("上一篇" in text and "下一篇" in text)
            ):
                end = index
                break
        if end is None:
            raise RuntimeError("目标文章缺少上一篇/下一篇结束边界")
        matches.append(
            (
                parent_source,
                ordered[start:end],
                ordered[start],
                ordered[end],
            )
        )
    if len(matches) != 1:
        raise RuntimeError(f"目标文章边界必须唯一，实际{len(matches)}个")
    return matches[0]


def _collect_candidates(documents, site, spec) -> tuple[Candidate, ...]:
    issue_regex = re.compile(spec.issue_pattern)
    value_regex = re.compile(spec.value_pattern)
    candidates = []
    for document in documents:
        text = html_to_text(document.content)
        issue_matches = list(issue_regex.finditer(text))
        for index, issue_match in enumerate(issue_matches):
            issue_text = issue_match.groupdict().get("issue") or issue_match.group(0)
            issue_digits = re.search(r"\d{1,4}", issue_text)
            if issue_digits is None:
                continue
            segment_end = (
                issue_matches[index + 1].start()
                if index + 1 < len(issue_matches)
                else len(text)
            )
            segment = text[issue_match.start():segment_end]
            normalized_segment = normalize_text(segment)
            keyword_matches = [
                match
                for keyword in spec.keywords
                for match in re.finditer(re.escape(keyword), segment)
            ]
            if not keyword_matches:
                continue
            first_keyword_start = min(match.start() for match in keyword_matches)
            keyword_end = max(
                match.end()
                for match in keyword_matches
                if match.start() == first_keyword_start
            )
            for value_match in value_regex.finditer(segment, keyword_end):
                raw_value = (
                    value_match.groupdict().get("value") or value_match.group(0)
                )
                value = normalize_half_wave(raw_value)
                if value is None:
                    continue
                candidates.append(
                    Candidate(
                        issue=int(issue_digits.group(0)),
                        value=value,
                        document=document,
                        offset=issue_match.start() + value_match.start(),
                        snippet=normalized_segment[:180],
                    )
                )
    return tuple(candidates)


def main() -> int:
    sites, specs, _ = _load_runtime()
    site = sites.get(SITE_ID)
    spec = next(item for item in specs if item.site_id == SITE_ID)
    if site.direction != Direction.BOTTOM or spec.direction != Direction.BOTTOM:
        raise RuntimeError("守株待兔正式方向必须为bottom")
    fetched = default_document_provider(site, spec, ARTICLE_ISSUE)
    parent, article_documents, start_document, end_document = _article_documents(
        fetched.documents, site, spec
    )
    candidates = _collect_candidates(article_documents, site, spec)
    window, boundary_issues = select_directional_window(
        candidates,
        issue_of=lambda candidate: candidate.issue,
        direction=site.direction,
    )

    cases = []
    for issue in VALIDATION_ISSUES:
        in_window = tuple(item for item in window if item.issue == issue)
        values = sorted({item.value for item in in_window})
        passed = len(values) == 1
        cases.append(
            {
                "issue": issue,
                "passed": passed,
                "value": values[0] if passed else None,
                "failure": (
                    None
                    if passed
                    else (
                        "same_period_conflict"
                        if len(values) > 1
                        else "target_period_missing_or_outside_bottom_window"
                    )
                ),
            }
        )

    target_all = [item for item in candidates if item.issue == ARTICLE_ISSUE]
    report = {
        "site_id": SITE_ID,
        "site_name": site.name,
        "url": site.url,
        "record_id": extract_record_id(site.url),
        "direction": site.direction.value,
        "document_count": len(fetched.documents),
        "parent_script": parent,
        "article_boundary": {
            "start_order": start_document.order,
            "start_url": start_document.source_url,
            "end_order_exclusive": end_document.order,
            "end_url_exclusive": end_document.source_url,
        },
        "candidate_count": len(candidates),
        "boundary_issues": list(boundary_issues),
        "bottom_window": [
            {
                "issue": item.issue,
                "value": item.value,
                "document_order": item.document.order,
                "source_url": item.document.source_url,
                "snippet": item.snippet,
            }
            for item in window
        ],
        "target_all_diagnostics": [
            {
                "issue": item.issue,
                "value": item.value,
                "document_order": item.document.order,
                "source_url": item.document.source_url,
                "inside_bottom_window": item in window,
            }
            for item in target_all
        ],
        "cases": cases,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    target_case = next(item for item in cases if item["issue"] == ARTICLE_ISSUE)
    return 0 if target_case["passed"] and target_case["value"] == "绿单" else 1


if __name__ == "__main__":
    raise SystemExit(main())
