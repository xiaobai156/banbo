import json
import unittest
from pathlib import Path

from banbo.application.single_period import build_site_spec
from banbo.domain import (
    Direction,
    Document,
    DocumentSource,
    FailureCode,
    SiteSpec,
    ValidatedResult,
    validate_evidence,
)
from banbo.parsers.article_sibling_segment import ArticleSiblingSegmentParser
from banbo.parsers.protocol import ParserSpec
from banbo.parsers.specs import parse_parser_specs
from banbo.storage.site_repository import SiteRepository


BASE_DIR = Path(__file__).resolve().parents[2]


def _document(order, suffix, content, *, parent="article.js"):
    return Document(
        document_id=f"doc-{parent}-{suffix}",
        source=DocumentSource.SCRIPT,
        source_url=f"https://data.test/{parent}#decoded-{suffix}",
        order=order,
        content=content,
    )


def _spec():
    return ParserSpec(
        site_id="hw-test",
        strategy="article_sibling_segment",
        parser_version="1",
        parser_id="hw-test:article_sibling_segment:v1",
        direction=Direction.BOTTOM,
        anchors=("守株待兔",),
        keywords=("精杀半波", "半波"),
        issue_pattern=r"(?P<issue>\d{1,4})期",
        value_pattern=r"(?P<value>[红绿蓝]\s*(?:波\s*)?[单双])",
        options={
            "end_markers": ["上一篇", "下一篇"],
            "window_size": 3,
        },
    )


def _site():
    return SiteSpec(
        site_id="hw-test",
        name="守株待兔",
        url="https://example.test/topic/626099.html",
        direction=Direction.BOTTOM,
        strategy="article_sibling_segment",
        anchors=("守株待兔",),
        parser_version="1",
        keywords=("精杀半波", "半波"),
        value_pattern=r"(?P<value>[红绿蓝]\s*(?:波\s*)?[单双])",
    )


class ArticleSiblingSegmentParserTest(unittest.TestCase):
    def test_bottom_window_excludes_earlier_same_issue(self):
        documents = (
            _document(0, 18, "217期: 守株待兔 精杀半波"),
            _document(1, 30, "217期 精杀半波 红单 开:猴46准"),
            _document(
                2,
                66,
                "215期 精杀半波 红双 216期 精杀半波 绿双 "
                "217期 精杀半波 绿单",
            ),
            _document(3, 67, "context_switch 上一篇 下一篇"),
        )
        parser = ArticleSiblingSegmentParser(_spec())

        evidence = parser.parse(_site(), documents, 217)
        outcome = validate_evidence(_site(), 217, evidence)

        self.assertIsInstance(outcome, ValidatedResult)
        self.assertEqual("绿单", outcome.value)
        self.assertEqual((215, 216, 217), outcome.evidence.boundary_issues)

    def test_wrong_field_before_keyword_is_ignored(self):
        documents = (
            _document(0, 18, "217期: 守株待兔 精杀半波"),
            _document(
                1,
                66,
                "215期 精杀半波 红双 216期 精杀半波 绿双 "
                "217期 杀一肖 红单 精杀半波 绿单",
            ),
            _document(2, 67, "上一篇 下一篇"),
        )

        evidence = ArticleSiblingSegmentParser(_spec()).parse(
            _site(), documents, 217
        )
        outcome = validate_evidence(_site(), 217, evidence)

        self.assertIsInstance(outcome, ValidatedResult)
        self.assertEqual("绿单", outcome.value)

    def test_two_values_inside_bottom_window_remain_conflict(self):
        documents = (
            _document(0, 18, "217期: 守株待兔 精杀半波"),
            _document(
                1,
                66,
                "215期 精杀半波 红双 216期 精杀半波 绿双 "
                "217期 精杀半波 红单 精杀半波 绿单",
            ),
            _document(2, 67, "上一篇 下一篇"),
        )

        evidence = ArticleSiblingSegmentParser(_spec()).parse(
            _site(), documents, 217
        )
        outcome = validate_evidence(_site(), 217, evidence)

        self.assertEqual(FailureCode.SAME_PERIOD_CONFLICT, outcome.code)

    def test_navigation_end_excludes_next_article(self):
        documents = (
            _document(0, 18, "217期: 守株待兔 精杀半波"),
            _document(1, 66, "215期 精杀半波 红双 216期 精杀半波 绿双 217期 精杀半波 绿单"),
            _document(2, 67, "上一篇 下一篇"),
            _document(3, 68, "217期 精杀半波 蓝双"),
        )

        evidence = ArticleSiblingSegmentParser(_spec()).parse(
            _site(), documents, 217
        )
        outcome = validate_evidence(_site(), 217, evidence)

        self.assertIsInstance(outcome, ValidatedResult)
        self.assertEqual("绿单", outcome.value)

    def test_anchor_cannot_be_borrowed_across_parent_scripts(self):
        documents = (
            _document(0, 18, "217期: 守株待兔 精杀半波", parent="title.js"),
            _document(1, 19, "上一篇 下一篇", parent="title.js"),
            _document(2, 1, "217期 精杀半波 蓝双", parent="other.js"),
        )

        evidence = ArticleSiblingSegmentParser(_spec()).parse(
            _site(), documents, 217
        )
        outcome = validate_evidence(_site(), 217, evidence)

        self.assertEqual(FailureCode.TARGET_PERIOD_MISSING, outcome.code)

    def test_missing_end_boundary_is_rejected(self):
        documents = (
            _document(0, 18, "217期: 守株待兔 精杀半波"),
            _document(1, 66, "217期 精杀半波 绿单"),
        )

        evidence = ArticleSiblingSegmentParser(_spec()).parse(
            _site(), documents, 217
        )
        outcome = validate_evidence(_site(), 217, evidence)

        self.assertEqual(FailureCode.TARGET_PERIOD_MISSING, outcome.code)

    def test_out_of_window_issue_is_rejected(self):
        documents = (
            _document(0, 18, "217期: 守株待兔 精杀半波"),
            _document(1, 66, "214期 精杀半波 红单 215期 精杀半波 红双 216期 精杀半波 绿双 217期 精杀半波 绿单"),
            _document(2, 67, "上一篇 下一篇"),
        )

        evidence = ArticleSiblingSegmentParser(_spec()).parse(
            _site(), documents, 214
        )
        outcome = validate_evidence(_site(), 214, evidence)

        self.assertEqual(FailureCode.TARGET_PERIOD_MISSING, outcome.code)


class ShouzhudaituFormalSpecContractTest(unittest.TestCase):
    def test_formal_spec_uses_article_sibling_segment(self):
        sites = SiteRepository.from_json(BASE_DIR / "config" / "sites.json")
        specs = parse_parser_specs(
            json.loads(
                (BASE_DIR / "config" / "parser_specs.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        site = sites.get("hw-0141")
        spec = next(item for item in specs if item.site_id == "hw-0141")

        self.assertEqual("article_sibling_segment", spec.strategy)
        self.assertEqual(["上一篇", "下一篇"], spec.options["end_markers"])
        self.assertEqual(Direction.BOTTOM, build_site_spec(site, spec).direction)


if __name__ == "__main__":
    unittest.main()
