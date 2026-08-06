import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

from banbo.domain import Direction, SiteSpec, ValidatedResult, validate_evidence
from banbo.fetch import (
    DiscoveryOptions,
    DocumentDiscoverer,
    DynamicSourceSpec,
    HttpClient,
    fetch_dynamic_document,
)
from banbo.parsers import build_default_registry, parse_parser_specs


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get("BANBO_LIVE") == "1", "需要BANBO_LIVE=1")
class MigratedSpecsLiveTest(unittest.TestCase):
    def test_migrated_specs_match_latest_cached_period(self):
        raw_sites = json.loads(
            (ROOT / "config" / "sites.json").read_text(encoding="utf-8")
        )["sites"]
        sites_by_id = {
            item["site_id"]: item
            for item in raw_sites
        }
        cache = json.loads(
            (ROOT / "recent_10_cache.json").read_text(encoding="utf-8-sig")
        )
        target_issue = int(os.environ.get("BANBO_LIVE_ISSUE", cache["issues"][0]))
        expected_by_name = {
            item["name"]: item["values"].get(str(target_issue))
            for item in cache["sites"]
        }
        specs = parse_parser_specs(
            json.loads(
                (ROOT / "config" / "parser_specs.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        registry = build_default_registry()
        for spec in specs:
            registry.bind(spec)
        options = DiscoveryOptions(
            allowed_external_hosts=tuple(
                f"xia0{index}.cosds.ahsccn.com" for index in range(1, 7)
            ),
            script_path_markers=("/upload/script/", "/template/tags/", "/tags/"),
        )
        failures = []

        def verify(spec):
            raw = sites_by_id[spec.site_id]
            expected = expected_by_name.get(raw["name"])
            if expected is None:
                return None
            site = SiteSpec(
                site_id=spec.site_id,
                name=raw["name"],
                url=raw["url"],
                direction=Direction(raw["direction"]),
                strategy=spec.strategy,
                anchors=spec.anchors,
                keywords=spec.keywords,
                issue_pattern=spec.issue_pattern,
                value_pattern=spec.value_pattern,
                before_documents=spec.before_documents,
                after_documents=spec.after_documents,
                target_only=spec.target_only,
                record_id_pattern=spec.record_id_pattern,
                topic_id_pattern=spec.topic_id_pattern,
                parser_version=spec.parser_version,
            )
            source_options = spec.options.get("source")
            with HttpClient(timeout=20, retries=1) as client:
                if isinstance(source_options, dict):
                    document = fetch_dynamic_document(
                        client,
                        site.url,
                        target_issue,
                        DynamicSourceSpec(
                            kind=str(source_options["kind"]),
                            user_id=str(source_options["user_id"]),
                            topic=str(source_options["topic"]),
                            sub_topic=(
                                None
                                if source_options.get("sub_topic") is None
                                else str(source_options["sub_topic"])
                            ),
                        ),
                    )
                    site = replace(site, expected_record_id=document.record_id)
                    documents = (document,)
                else:
                    documents = DocumentDiscoverer(client).discover(
                        site.url,
                        options=options,
                        record_id_pattern=(
                            spec.record_id_pattern or spec.topic_id_pattern
                        ),
                    )
                    expected_record_id = next(
                        (
                            document.record_id
                            for document in documents
                            if document.source.value == "page"
                            and document.record_id is not None
                        ),
                        None,
                    )
                    site = replace(site, expected_record_id=expected_record_id)
            evidence = registry.parse(site, documents, target_issue)
            result = validate_evidence(site, target_issue, evidence)
            actual = result.value if isinstance(result, ValidatedResult) else None
            if actual != expected:
                return (
                    f"{raw['name']}: expected={expected} actual={actual} "
                    f"result={result}"
                )
            return None

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(verify, spec): spec for spec in specs}
            for future in as_completed(futures):
                try:
                    failure = future.result()
                except Exception as exc:
                    spec = futures[future]
                    failure = f"{spec.site_id}: {type(exc).__name__}: {exc}"
                if failure:
                    failures.append(failure)

        if failures:
            print("\n" + "\n".join(sorted(failures)))
        self.assertEqual([], sorted(failures))


if __name__ == "__main__":
    unittest.main()
