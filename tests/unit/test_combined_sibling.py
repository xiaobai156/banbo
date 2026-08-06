import unittest
from dataclasses import replace

from banbo.domain import (
    Direction,
    Document,
    DocumentSource,
    FailureCode,
    SiteSpec,
    ValidatedResult,
    validate_evidence,
)
from banbo.parsers.combined_sibling import CombinedSiblingParser
from banbo.parsers.protocol import ParserSpec


def document(order, suffix, content, *, parent="post.js"):
    return Document(
        document_id=f"doc-{order}",
        source=DocumentSource.SCRIPT,
        source_url=f"https://data.test/{parent}#decoded-{suffix}",
        order=order,
        content=content,
    )


def site_spec(direction=Direction.TOP):
    return SiteSpec(
        site_id="hw-test",
        name="满堂红",
        url="https://example.test/",
        direction=direction,
        strategy="combined_sibling",
        anchors=("澳门 满 堂 红", "稳杀半波"),
        parser_version="1",
        keywords=("稳杀半波",),
    )


class CombinedSiblingParserTest(unittest.TestCase):
    def test_compact_anchor_and_cross_fragment_row(self):
        spec = ParserSpec(
            site_id="hw-test",
            strategy="combined_sibling",
            parser_version="1",
            direction=Direction.TOP,
            anchors=("澳门 满 堂 红", "稳杀半波"),
            keywords=("稳杀半波",),
            options={
                "patterns": [
                    "(?<!\\d){issue}期[^期]{0,60}"
                    "(?P<value>[红绿蓝](?:波)?[单双])"
                ],
                "compact": True,
                "anchor_mode": "all",
                "skip_keyword_check": True,
            },
        )
        documents = (
            document(0, 1, "澳门 满 堂 红 稳杀半波"),
            document(1, 2, "215期 稳杀半波 蓝"),
            document(2, 3, "单 开000中 214期 稳杀半波"),
            document(3, 4, "红双 开兔04错 213期 绿单"),
        )

        evidence = CombinedSiblingParser(spec).parse(
            site_spec(), documents, 215
        )
        outcome = validate_evidence(site_spec(), 215, evidence)

        self.assertIsInstance(outcome, ValidatedResult)
        self.assertEqual("蓝单", outcome.value)
        self.assertIn(
            outcome.evidence.document_relation,
            {"same_document", "declared_neighbor_window"},
        )
        self.assertIn("#decoded-2", outcome.evidence.source_url)

    def test_history_rows_can_bind_issue_and_value_in_different_fragments(self):
        spec = ParserSpec(
            site_id="hw-test",
            strategy="combined_sibling",
            parser_version="1",
            direction=Direction.TOP,
            anchors=("王中王", "禁半波"),
            keywords=("禁半波",),
            options={
                "compact": True,
                "anchor_mode": "all",
                "skip_keyword_check": True,
            },
        )
        site = replace(
            site_spec(),
            name="王中王",
            anchors=("王中王", "禁半波"),
            keywords=("禁半波",),
        )
        documents = (
            document(0, 1, "王中王"),
            document(1, 2, "期数 禁半波"),
            document(2, 3, "215期 猪肖"),
            document(3, 4, "蓝双 开00准 214期 马肖"),
            document(4, 5, "绿单 开04准 213期 牛肖 红双"),
        )

        evidence = CombinedSiblingParser(spec).parse(
            site, documents, 215
        )
        outcome = validate_evidence(site, 215, evidence)

        self.assertIsInstance(outcome, ValidatedResult)
        self.assertEqual("蓝双", outcome.value)

    def test_anchors_cannot_be_borrowed_from_another_parent(self):
        spec = ParserSpec(
            site_id="hw-test",
            strategy="combined_sibling",
            parser_version="1",
            direction=Direction.TOP,
            anchors=("满堂红", "稳杀半波"),
            keywords=(),
            options={"compact": True, "skip_keyword_check": True},
        )
        documents = (
            document(0, 1, "满堂红", parent="title.js"),
            document(1, 2, "215期 蓝单", parent="body.js"),
        )

        evidence = CombinedSiblingParser(spec).parse(
            site_spec(), documents, 215
        )
        outcome = validate_evidence(site_spec(), 215, evidence)

        self.assertEqual(FailureCode.TARGET_PERIOD_MISSING, outcome.code)

    def test_anchor_same_document_uses_html_text(self):
        spec = ParserSpec(
            site_id="hw-test",
            strategy="combined_sibling",
            parser_version="1",
            direction=Direction.TOP,
            anchors=("澳门 满堂 红", "稳杀半波"),
            keywords=(),
            options={
                "patterns": [
                    "(?P<_issue>\\d{1,3})期[^期]{0,40}稳杀半波"
                    "[^期]{0,20}(?P<value>[红绿蓝][单双])"
                ],
                "compact": True,
                "anchor_mode": "all",
                "anchor_same_document": True,
                "skip_keyword_check": True,
            },
        )
        documents = (
            document(
                0,
                1,
                "<span>澳门</span><span>满</span><span>堂</span>"
                "<span>红</span><b>稳杀半波</b>",
            ),
            document(1, 2, "215期:稳杀半波【蓝单】开0000中214期:稳杀半波【蓝双】"),
            document(2, 3, "213期:稳杀半波【红双】"),
        )

        evidence = CombinedSiblingParser(spec).parse(
            site_spec(), documents, 215
        )
        outcome = validate_evidence(site_spec(), 215, evidence)

        self.assertIsInstance(outcome, ValidatedResult)
        self.assertEqual("蓝单", outcome.value)

    def test_compact_numeric_fragment_boundary_does_not_fuse_periods(self):
        spec = ParserSpec(
            site_id="hw-test",
            strategy="combined_sibling",
            parser_version="1",
            direction=Direction.TOP,
            anchors=("汉锺离", "综合绝杀"),
            issue_pattern=r"(?P<issue>\d{1,3})期",
            value_pattern=r"(?P<value>[红绿蓝](?:波)?[单双])",
            keywords=(),
            options={
                "compact": True,
                "anchor_mode": "all",
                "skip_keyword_check": True,
            },
        )
        site = replace(
            site_spec(),
            name="汉锺离",
            anchors=("汉锺离", "综合绝杀"),
            keywords=(),
        )
        documents = (
            document(0, 1, "汉锺离 综合绝杀"),
            document(1, 2, "期数 杀半波"),
            document(2, 3, "215期 鼠 红单 4尾 开000 214期 马"),
            document(3, 4, "蓝单 6尾 开兔04 213期 鼠 绿双 7尾 开猴35"),
        )

        parser = CombinedSiblingParser(spec)
        for issue, expected in ((215, "红单"), (214, "蓝单")):
            evidence = parser.parse(site, documents, issue)
            outcome = validate_evidence(site, issue, evidence)
            self.assertIsInstance(outcome, ValidatedResult)
            self.assertEqual(expected, outcome.value)
            self.assertEqual((215, 214, 213), outcome.evidence.boundary_issues)


if __name__ == "__main__":
    unittest.main()
