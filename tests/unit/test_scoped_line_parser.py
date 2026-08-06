import unittest

from banbo.domain.models import Direction, Document, DocumentSource, SiteSpec
from banbo.parsers.protocol import ParserSpec
from banbo.parsers.scoped_line import ScopedLineParser


class ScopedLineParserTest(unittest.TestCase):
    def site(self):
        return SiteSpec(
            site_id="line-site",
            name="行站",
            url="https://example.test/topic/1.html",
            direction=Direction.TOP,
            strategy="scoped_line",
            anchors=("专属标题",),
            keywords=("半波",),
            parser_version="1",
        )

    def parser(self, **options):
        return ScopedLineParser(
            ParserSpec(
                site_id="line-site",
                strategy="scoped_line",
                parser_version="1",
                anchors=("专属标题",),
                keywords=("半波",),
                value_pattern=r"(?P<value>[红绿蓝]\s*(?:波\s*)?[单双])",
                options=options,
            )
        )

    def document(self, content):
        return Document(
            document_id="doc",
            source=DocumentSource.PAGE,
            source_url="https://example.test/topic/1.html",
            order=0,
            content=content,
        )

    def test_extracts_only_target_issue_segment(self):
        evidence = self.parser().parse(
            self.site(),
            (
                self.document(
                    "专属标题 211期杀半波【红 波双】开00准 "
                    "210期杀半波【绿单】开49准"
                ),
            ),
            211,
        )

        self.assertEqual(["红双"], [item.value for item in evidence])

    def test_uses_value_after_marker_not_unrelated_value_before_marker(self):
        evidence = self.parser(marker="+++杀").parse(
            self.site(),
            (
                self.document(
                    "专属标题 211期杀【3头单】+++杀【红单】开00准"
                ),
            ),
            211,
        )

        self.assertEqual(["红单"], [item.value for item in evidence])

    def test_conflicting_values_in_target_segment_are_preserved(self):
        evidence = self.parser().parse(
            self.site(),
            (
                self.document(
                    "专属标题 211期杀半波【红单】【绿双】开00准"
                ),
            ),
            211,
        )

        self.assertEqual({"红单", "绿双"}, {item.value for item in evidence})


if __name__ == "__main__":
    unittest.main()
