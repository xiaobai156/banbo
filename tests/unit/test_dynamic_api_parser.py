import unittest

from banbo.domain.models import Direction, Document, DocumentSource, SiteSpec
from banbo.parsers.dynamic_api import DynamicApiParser
from banbo.parsers.protocol import ParserSpec


class DynamicApiParserTest(unittest.TestCase):
    def setUp(self):
        self.site = SiteSpec(
            site_id="api-site",
            name="接口站",
            url="https://example.test/article/admin/222",
            direction=Direction.TOP,
            strategy="dynamic_api",
            anchors=("接口站", "绝杀半波"),
            keywords=("绝杀半波",),
            parser_version="1",
            expected_record_id="222",
        )
        self.parser = DynamicApiParser(
            ParserSpec(
                site_id="api-site",
                strategy="dynamic_api",
                parser_version="1",
                anchors=("接口站", "绝杀半波"),
                keywords=("绝杀半波",),
            )
        )

    def document(self, order, record_id, value, source=DocumentSource.API):
        return Document(
            document_id=f"doc-{order}",
            source=source,
            source_url=f"https://example.test/api/{record_id}",
            order=order,
            content=f"接口站 209期 绝杀半波【{value}】",
            record_id=record_id,
        )

    def test_ignores_same_issue_bait_from_other_record(self):
        documents = (
            self.document(0, "111", "红单"),
            self.document(1, "222", "绿双"),
        )

        evidence = self.parser.parse(self.site, documents, 209)

        self.assertEqual(["绿双"], [item.value for item in evidence])
        self.assertEqual("222", evidence[0].record_id)

    def test_browser_fallback_still_requires_exact_record_id(self):
        documents = (
            self.document(0, "111", "红单", DocumentSource.BROWSER),
        )

        evidence = self.parser.parse(self.site, documents, 209)

        self.assertEqual((), evidence)


if __name__ == "__main__":
    unittest.main()
