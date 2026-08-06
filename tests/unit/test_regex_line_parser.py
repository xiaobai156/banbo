import unittest

from banbo.domain.models import Direction, Document, DocumentSource, SiteSpec
from banbo.parsers.protocol import ParserSpec
from banbo.parsers.regex_line import RegexLineParser


class RegexLineParserTest(unittest.TestCase):
    def site(self, direction=Direction.TOP):
        return SiteSpec(
            site_id="regex-site",
            name="格式站",
            url="https://example.test/topic/1.html",
            direction=direction,
            strategy="regex_line",
            anchors=("专属格式",),
            keywords=("半波",),
            parser_version="1",
        )

    def parser(self, patterns, **options):
        return RegexLineParser(
            ParserSpec(
                site_id="regex-site",
                strategy="regex_line",
                parser_version="1",
                anchors=("专属格式",),
                keywords=("半波",),
                options={"patterns": patterns, **options},
            )
        )

    def document(self, order, content):
        return Document(
            document_id=f"doc-{order}",
            source=DocumentSource.SCRIPT,
            source_url=f"https://example.test/{order}.js",
            order=order,
            content=content,
        )

    def test_substitutes_target_issue_and_extracts_named_value(self):
        parser = self.parser(
            [r"{issue}期\s*专属格式\s*【(?P<value>[红绿蓝](?:波)?[单双])】"]
        )

        evidence = parser.parse(
            self.site(),
            (self.document(0, "210期专属格式【红单】 211期专属格式【绿双】"),),
            211,
        )

        self.assertEqual(["绿双"], [item.value for item in evidence])

    def test_document_anchor_prevents_global_bait_match(self):
        parser = self.parser(
            [r"{issue}期\s*【(?P<value>[红绿蓝](?:波)?[单双])】"]
        )

        evidence = parser.parse(
            self.site(),
            (
                self.document(0, "其它栏目 211期【红单】"),
                self.document(1, "专属格式 211期【绿双】"),
            ),
            211,
        )

        self.assertEqual(["绿双"], [item.value for item in evidence])

    def test_same_period_conflict_is_preserved(self):
        parser = self.parser(
            [r"{issue}期\s*专属格式\s*【(?P<value>[红绿蓝](?:波)?[单双])】"]
        )

        evidence = parser.parse(
            self.site(),
            (
                self.document(
                    0,
                    "211期专属格式【绿双】 211期专属格式【红单】",
                ),
            ),
            211,
        )

        self.assertEqual({"绿双", "红单"}, {item.value for item in evidence})

    def test_compact_mode_handles_decorative_spacing(self):
        parser = self.parser(
            [r"{issue}期绝杀半波【(?P<value>[红绿蓝](?:波)?[单双])】"],
            compact=True,
        )

        evidence = parser.parse(
            self.site(),
            (self.document(0, "专属格式 211 期 绝 杀 半 波【蓝 波 双】"),),
            211,
        )

        self.assertEqual(["蓝双"], [item.value for item in evidence])

    def test_top_window_rejects_target_in_fourth_issue_group(self):
        parser = self.parser(
            [r"{issue}期\s*专属格式【(?P<value>[红绿蓝](?:波)?[单双])】"]
        )

        evidence = parser.parse(
            self.site(),
            (
                self.document(
                    0,
                    "专属格式 209期专属格式【红单】 "
                    "208期专属格式【红双】 "
                    "207期专属格式【绿单】 "
                    "206期专属格式【蓝双】",
                ),
            ),
            206,
        )

        self.assertEqual((), evidence)

    def test_bottom_window_accepts_target_in_last_three_issue_groups(self):
        parser = self.parser(
            [r"{issue}期\s*专属格式【(?P<value>[红绿蓝](?:波)?[单双])】"]
        )

        evidence = parser.parse(
            self.site(Direction.BOTTOM),
            (
                self.document(
                    0,
                    "专属格式 209期专属格式【红单】 "
                    "208期专属格式【红双】 "
                    "207期专属格式【绿单】 "
                    "206期专属格式【蓝双】",
                ),
            ),
            206,
        )

        self.assertEqual(["蓝双"], [item.value for item in evidence])
        self.assertEqual((208, 207, 206), evidence[0].boundary_issues)


if __name__ == "__main__":
    unittest.main()
