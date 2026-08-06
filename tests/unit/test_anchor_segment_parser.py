import unittest

from banbo.domain.models import Direction, Document, DocumentSource, SiteSpec
from banbo.parsers.anchor_segment import AnchorSegmentParser
from banbo.parsers.protocol import ParserSpec


class AnchorSegmentParserTest(unittest.TestCase):
    def setUp(self):
        self.site = SiteSpec(
            site_id="segment-site",
            name="作者站",
            url="https://example.test/topic/1.html",
            direction=Direction.BOTTOM,
            strategy="anchor_segment",
            anchors=("作者站",),
            keywords=("绝杀半波",),
            parser_version="1",
        )
        self.parser = AnchorSegmentParser(
            ParserSpec(
                site_id="segment-site",
                strategy="anchor_segment",
                parser_version="1",
                anchors=("作者站",),
                keywords=("绝杀半波",),
                options={"max_issues": 4, "window_size": 3},
            )
        )

    def document(self, content):
        return Document(
            document_id="doc",
            source=DocumentSource.SCRIPT,
            source_url="https://example.test/data.js",
            order=0,
            content=content,
        )

    def test_only_reads_issue_block_after_anchor(self):
        content = (
            "209期绝杀半波【红单】 其它栏目 "
            "作者站 207期绝杀半波【蓝单】 "
            "208期绝杀半波【绿单】 209期绝杀半波【绿双】 "
            "210期绝杀半波【红双】 211期绝杀半波【蓝双】 "
            "212期绝杀半波【红单】"
        )

        evidence = self.parser.parse(
            self.site, (self.document(content),), 210
        )

        self.assertEqual(["红双"], [item.value for item in evidence])

    def test_target_outside_bounded_issue_block_is_rejected(self):
        content = (
            "作者站 207期绝杀半波【蓝单】 "
            "208期绝杀半波【绿单】 209期绝杀半波【绿双】 "
            "210期绝杀半波【红双】 211期绝杀半波【蓝双】"
        )

        evidence = self.parser.parse(
            self.site, (self.document(content),), 211
        )

        self.assertEqual((), evidence)


if __name__ == "__main__":
    unittest.main()
