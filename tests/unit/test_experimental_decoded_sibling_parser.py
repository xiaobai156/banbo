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
from banbo.parsers.decoded_sibling import DecodedSiblingParser
from banbo.parsers.protocol import ParserSpec


def document(order, suffix, content, *, parent="post.js"):
    return Document(
        document_id=f"doc-{order}",
        source=DocumentSource.SCRIPT,
        source_url=f"https://data.test/{parent}#decoded-{suffix}",
        order=order,
        content=content,
    )


def parser_spec(direction=Direction.BOTTOM):
    return ParserSpec(
        site_id="hw-test",
        strategy="decoded_sibling",
        parser_version="1",
        parser_id="hw-test:decoded_sibling:v1",
        direction=direction,
        anchors=("龙行虎变",),
        keywords=("绝杀半波",),
    )


def site_spec(direction=Direction.BOTTOM):
    return SiteSpec(
        site_id="hw-test",
        name="龙行虎变",
        url="https://example.test/topic/1.html",
        direction=direction,
        strategy="decoded_sibling",
        anchors=("龙行虎变",),
        parser_version="1",
        keywords=("绝杀半波",),
    )


class ExperimentalDecodedSiblingParserTest(unittest.TestCase):
    def test_bottom_uses_last_three_rows_from_same_parent_script(self):
        spec = parser_spec()
        site = site_spec()
        documents = (
            document(0, 1, "215期【绝杀半波】作者：龙行虎变"),
            document(1, 2, "212期：绝杀半波（红单）"),
            document(2, 3, "213期：绝杀半波（蓝双）"),
            document(3, 4, "214期：绝杀半波（绿单）"),
            document(4, 5, "215期：绝杀半波（蓝单）"),
        )

        evidence = DecodedSiblingParser(spec).parse(site, documents, 215)
        outcome = validate_evidence(site, 215, evidence)

        self.assertIsInstance(outcome, ValidatedResult)
        self.assertEqual("蓝单", outcome.value)
        self.assertEqual((213, 214, 215), outcome.evidence.boundary_issues)
        self.assertEqual("declared_neighbor_window", outcome.evidence.document_relation)

    def test_does_not_borrow_anchor_from_another_parent_script(self):
        spec = parser_spec()
        site = site_spec()
        documents = (
            document(0, 1, "龙行虎变 绝杀半波", parent="title.js"),
            document(1, 1, "215期：绝杀半波（蓝单）", parent="body.js"),
        )

        evidence = DecodedSiblingParser(spec).parse(site, documents, 215)
        outcome = validate_evidence(site, 215, evidence)

        self.assertEqual(FailureCode.TARGET_PERIOD_MISSING, outcome.code)

    def test_rejects_target_outside_configured_direction_window(self):
        spec = parser_spec(Direction.TOP)
        site = site_spec(Direction.TOP)
        documents = (
            document(0, 1, "龙行虎变 绝杀半波"),
            document(1, 2, "212期：绝杀半波（红单）"),
            document(2, 3, "213期：绝杀半波（蓝双）"),
            document(3, 4, "214期：绝杀半波（绿单）"),
            document(4, 5, "215期：绝杀半波（蓝单）"),
        )

        evidence = DecodedSiblingParser(spec).parse(site, documents, 215)
        outcome = validate_evidence(site, 215, evidence)

        self.assertEqual(FailureCode.TARGET_PERIOD_MISSING, outcome.code)

    def test_same_period_different_values_remain_a_conflict(self):
        spec = parser_spec()
        site = site_spec()
        documents = (
            document(0, 1, "龙行虎变 绝杀半波"),
            document(1, 2, "213期：绝杀半波（红单）"),
            document(2, 3, "214期：绝杀半波（绿双）"),
            document(3, 4, "215期：绝杀半波（蓝单） 绝杀半波（红双）"),
        )

        evidence = DecodedSiblingParser(spec).parse(site, documents, 215)
        outcome = validate_evidence(site, 215, evidence)

        self.assertEqual(FailureCode.SAME_PERIOD_CONFLICT, outcome.code)

    def test_configured_pattern_ignores_number_label_noise(self):
        spec = replace(
            parser_spec(),
            options={
                "patterns": [
                    "{issue}期[^期]{0,80}绝杀半波"
                    "(?P<value>[红绿蓝](?:波)?[单双])"
                ],
                "compact": True,
            },
        )
        site = site_spec()
        documents = (
            document(0, 1, "龙行虎变 绝杀半波"),
            document(1, 2, "213期 绝杀半波 红单"),
            document(2, 3, "214期 绝杀半波 绿双"),
            document(
                3,
                4,
                "215期 绝杀半波 蓝双 "
                "红单:01.07 蓝单:03.09 绿单:05.11",
            ),
        )

        evidence = DecodedSiblingParser(spec).parse(site, documents, 215)
        outcome = validate_evidence(site, 215, evidence)

        self.assertIsInstance(outcome, ValidatedResult)
        self.assertEqual("蓝双", outcome.value)

    def test_issue_pattern_does_not_match_suffix_of_a_larger_number(self):
        spec = replace(
            parser_spec(),
            options={
                "patterns": [
                    "(?<!\\d){issue}期[^期]{0,40}"
                    "(?P<value>[红绿蓝](?:波)?[单双])"
                ],
                "compact": True,
            },
        )
        site = site_spec()
        documents = (
            document(0, 1, "龙行虎变 绝杀半波"),
            document(1, 2, "4215期 红双"),
        )

        evidence = DecodedSiblingParser(spec).parse(site, documents, 215)
        outcome = validate_evidence(site, 215, evidence)

        self.assertEqual(FailureCode.TARGET_PERIOD_MISSING, outcome.code)

    def test_all_anchors_may_be_distributed_inside_one_parent_script(self):
        spec = replace(
            parser_spec(),
            anchors=("王中王", "禁半波"),
            keywords=(),
            options={
                "patterns": [
                    "(?<!\\d){issue}期[^期红绿蓝]{0,40}"
                    "(?P<value>[红绿蓝](?:波)?[单双])"
                ],
                "compact": True,
                "anchor_mode": "all",
            },
        )
        site = replace(
            site_spec(),
            anchors=("王中王", "禁半波"),
            keywords=(),
        )
        documents = (
            document(0, 1, "王中王"),
            document(1, 2, "禁半波"),
            document(2, 3, "213期 红单"),
            document(3, 4, "214期 绿双"),
            document(4, 5, "215期 蓝双"),
        )

        evidence = DecodedSiblingParser(spec).parse(site, documents, 215)
        outcome = validate_evidence(site, 215, evidence)

        self.assertIsInstance(outcome, ValidatedResult)
        self.assertEqual("蓝双", outcome.value)

    def test_explicit_keyword_skip_still_requires_all_group_anchors(self):
        spec = replace(
            parser_spec(),
            anchors=("魔童", "综合绝杀"),
            keywords=("页面没有这个词",),
            options={
                "patterns": [
                    "(?<!\\d){issue}期[^期红绿蓝]{0,40}"
                    "(?P<value>[红绿蓝](?:波)?[单双])"
                ],
                "compact": True,
                "anchor_mode": "all",
                "skip_keyword_check": True,
            },
        )
        site = replace(
            site_spec(),
            anchors=("魔童", "综合绝杀"),
            keywords=("页面没有这个词",),
        )
        documents = (
            document(0, 1, "魔童"),
            document(1, 2, "综合绝杀"),
            document(2, 3, "213期 红单"),
            document(3, 4, "214期 绿双"),
            document(4, 5, "215期 蓝双"),
        )

        evidence = DecodedSiblingParser(spec).parse(site, documents, 215)
        outcome = validate_evidence(site, 215, evidence)

        self.assertIsInstance(outcome, ValidatedResult)
        self.assertEqual("蓝双", outcome.value)


if __name__ == "__main__":
    unittest.main()
