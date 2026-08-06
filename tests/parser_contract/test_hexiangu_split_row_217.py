import json
import unittest
from pathlib import Path

from banbo.application.single_period import build_site_spec
from banbo.domain import (
    Document,
    DocumentSource,
    FailureCode,
    ValidatedResult,
    validate_evidence,
)
from banbo.parsers.combined_sibling import CombinedSiblingParser
from banbo.parsers.specs import parse_parser_specs
from banbo.storage.site_repository import SiteRepository


BASE_DIR = Path(__file__).resolve().parents[2]


def _document(order: int, suffix: int, content: str) -> Document:
    return Document(
        document_id=f"hexiangu-{order}",
        source=DocumentSource.SCRIPT,
        source_url=(
            "https://xia01.cosds.ahsccn.com/upload/script/08/"
            f"hexiangu.js#decoded-{suffix}"
        ),
        order=order,
        content=content,
    )


class HexianguSplitRow217ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sites = SiteRepository.from_json(BASE_DIR / "config" / "sites.json")
        specs = parse_parser_specs(
            json.loads(
                (BASE_DIR / "config" / "parser_specs.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        cls.site = sites.get("hw-0119")
        cls.spec = next(spec for spec in specs if spec.site_id == "hw-0119")
        cls.site_spec = build_site_spec(cls.site, cls.spec)
        cls.documents = (
            _document(0, 65, "<h2>绝杀专区 984440c.com</h2>"),
            _document(
                1,
                77,
                "<tr><th>期数</th><th>杀一肖</th><th>杀半波</th>"
                "<th>杀一尾</th><th>开奖结果</th></tr>"
                "<tr><td>217期</td><td>《马》</td>",
            ),
            _document(
                2,
                78,
                "<td>《蓝双》</td><td>《5尾》</td><td>开:?00</td></tr>"
                "<tr><td>216期</td><td>《猪》</td><td>《蓝单》</td>"
                "<td>《4尾》</td><td>开:马37</td></tr>",
            ),
            _document(
                3,
                79,
                "<tr><td>215期</td><td>《兔》</td><td>《红单》</td>"
                "<td>《5尾》</td><td>开:蛇14</td></tr>"
                "<tr><td>214期</td><td>《鼠》</td><td>《绿双》</td></tr>",
            ),
        )

    def test_formal_spec_uses_spaced_combined_sibling_parser(self):
        self.assertEqual("combined_sibling", self.spec.strategy)
        self.assertFalse(self.spec.options["compact"])

    def test_top_three_rows_parse_across_decoded_fragments(self):
        parser = CombinedSiblingParser(self.spec)
        expected = {217: "蓝双", 216: "蓝单", 215: "红单"}

        for issue, value in expected.items():
            with self.subTest(issue=issue):
                evidence = parser.parse(self.site_spec, self.documents, issue)
                outcome = validate_evidence(self.site_spec, issue, evidence)
                self.assertIsInstance(outcome, ValidatedResult)
                self.assertEqual(value, outcome.value)
                self.assertEqual((217, 216, 215), outcome.evidence.boundary_issues)

    def test_out_of_window_and_missing_issues_stay_failed(self):
        parser = CombinedSiblingParser(self.spec)

        for issue in (214, 999):
            with self.subTest(issue=issue):
                evidence = parser.parse(self.site_spec, self.documents, issue)
                outcome = validate_evidence(self.site_spec, issue, evidence)
                self.assertEqual(FailureCode.TARGET_PERIOD_MISSING, outcome.code)


if __name__ == "__main__":
    unittest.main()
