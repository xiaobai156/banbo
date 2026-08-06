from __future__ import annotations

import json

from banbo.application.single_period import build_site_spec, default_document_provider
from banbo.cli import _load_runtime
from banbo.domain import ValidatedResult, validate_evidence
from banbo.fetch.dynamic_records import extract_record_id


SITE_ID = "hw-0141"
ISSUES = (217, 216, 215, 214, 999)


def main() -> int:
    sites, specs, registry = _load_runtime()
    site_record = sites.get(SITE_ID)
    spec = next(item for item in specs if item.site_id == SITE_ID)
    site = build_site_spec(site_record, spec)
    documents = default_document_provider(site, spec, 217).documents

    checks = []
    expected = {217: "绿单", 216: "绿双", 215: "红双"}
    for issue in ISSUES:
        evidence = registry.parse(site, documents, issue)
        outcome = validate_evidence(site, issue, evidence)
        checks.append(
            {
                "issue": issue,
                "status": (
                    "success"
                    if isinstance(outcome, ValidatedResult)
                    else "failure"
                ),
                "value": (
                    outcome.value
                    if isinstance(outcome, ValidatedResult)
                    else None
                ),
                "failure_code": (
                    None
                    if isinstance(outcome, ValidatedResult)
                    else outcome.code.value
                ),
                "boundary_issues": (
                    list(outcome.evidence.boundary_issues)
                    if isinstance(outcome, ValidatedResult)
                    else []
                ),
            }
        )

    passed = all(
        (
            item["status"] == "success"
            and item["value"] == expected[item["issue"]]
            and item["boundary_issues"] == [215, 216, 217]
        )
        if item["issue"] in expected
        else item["status"] == "failure"
        for item in checks
    )
    report = {
        "site_id": site.site_id,
        "site_name": site.name,
        "url": site.url,
        "record_id": extract_record_id(site.url),
        "direction": site.direction.value,
        "parser_id": spec.parser_id,
        "document_count": len(documents),
        "checks": checks,
        "passed": passed,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
