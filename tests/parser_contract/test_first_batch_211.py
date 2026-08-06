import json
import unittest
from pathlib import Path

from banbo.domain import (
    Document,
    DocumentSource,
    SiteSpec,
    ValidatedResult,
    validate_evidence,
)
from banbo.parsers import build_default_registry
from banbo.parsers.specs import parse_parser_specs


ROOT = Path(__file__).resolve().parents[2]


class FirstBatchParserContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec_payload = json.loads(
            (ROOT / "config" / "parser_specs.json").read_text(
                encoding="utf-8"
            )
        )
        cls.specs = {
            spec.site_id: spec for spec in parse_parser_specs(spec_payload)
        }
        cls.fixture = json.loads(
            (ROOT / "tests" / "frozen_pages" / "first_batch_211.json").read_text(
                encoding="utf-8"
            )
        )

    def test_all_first_batch_sites_match_real_211_evidence(self):
        for case in self.fixture["cases"]:
            with self.subTest(site=case["name"]):
                spec = self.specs[case["site_id"]]
                site = SiteSpec(
                    site_id=case["site_id"],
                    name=case["name"],
                    url=case["url"],
                    direction=spec.direction,
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
                documents = self._documents(case)
                registry = build_default_registry()
                registry.bind(spec)

                evidence = registry.parse(
                    site, documents, self.fixture["issue"]
                )
                result = validate_evidence(
                    site, self.fixture["issue"], evidence
                )

                self.assertIsInstance(result, ValidatedResult)
                self.assertEqual(case["expected"], result.value)

    @staticmethod
    def _documents(case):
        if case.get("same_document"):
            return (
                Document(
                    document_id=f"{case['site_id']}-page",
                    source=DocumentSource.PAGE,
                    source_url=case["url"],
                    order=0,
                    content=case["content"],
                ),
            )

        documents = [
            Document(
                document_id=f"{case['site_id']}-bait",
                source=DocumentSource.SCRIPT,
                source_url=f"{case['url']}#bait",
                order=0,
                content="211期绝杀半波【红单】",
            ),
            Document(
                document_id=f"{case['site_id']}-anchor",
                source=DocumentSource.SCRIPT,
                source_url=f"{case['url']}#anchor",
                order=1,
                content=case["anchor_content"],
            ),
        ]
        for index in range(1, int(case["data_offset"])):
            documents.append(
                Document(
                    document_id=f"{case['site_id']}-gap-{index}",
                    source=DocumentSource.SCRIPT,
                    source_url=f"{case['url']}#gap-{index}",
                    order=len(documents),
                    content=f"结构占位文档{index}",
                )
            )
        documents.append(
            Document(
                document_id=f"{case['site_id']}-data",
                source=DocumentSource.SCRIPT,
                source_url=f"{case['url']}#data",
                order=len(documents),
                content=case["data_content"],
            )
        )
        return tuple(documents)


if __name__ == "__main__":
    unittest.main()
