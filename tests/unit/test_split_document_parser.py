import unittest

from banbo.domain.models import Direction, Document, DocumentSource, SiteSpec
from banbo.parsers.protocol import ParserSpec
from banbo.parsers.split_document import SplitDocumentParser


def doc(order, content, record_id=None):
    return Document(
        document_id=f"doc-{order}",
        source=DocumentSource.SCRIPT,
        source_url=f"https://example.test/{order}.js",
        order=order,
        content=content,
        record_id=record_id,
    )


class SplitDocumentParserTest(unittest.TestCase):
    def setUp(self):
        self.site = SiteSpec(
            site_id="split-site",
            name="分离站",
            url="https://example.test/topic/1.html",
            direction=Direction.TOP,
            strategy="split_document",
            anchors=("分离站",),
            keywords=("绝杀半波",),
            parser_version="1",
        )
        self.parser = SplitDocumentParser(
            ParserSpec(
                site_id="split-site",
                strategy="split_document",
                parser_version="1",
                anchors=("分离站",),
                keywords=("绝杀半波",),
                after_documents=1,
            )
        )

    def test_joins_only_explicit_target_title_and_neighbor_value(self):
        documents = (
            doc(0, "分离站 209期 绝杀半波"),
            doc(1, "开奖结果【绿双】"),
            doc(2, "其它栏目【红单】"),
        )

        evidence = self.parser.parse(self.site, documents, 209)

        self.assertEqual(["绿双"], [item.value for item in evidence])
        self.assertEqual("doc-1", evidence[0].document_id)

    def test_does_not_borrow_value_from_other_issue_document(self):
        documents = (
            doc(0, "分离站 209期 绝杀半波"),
            doc(1, "208期 开奖结果【绿双】"),
        )

        evidence = self.parser.parse(self.site, documents, 209)

        self.assertEqual((), evidence)

    def test_conflicting_values_in_same_explicit_scope_are_preserved(self):
        documents = (
            doc(0, "分离站 209期 绝杀半波【绿双】【红单】"),
        )

        evidence = self.parser.parse(self.site, documents, 209)

        self.assertEqual({"绿双", "红单"}, {item.value for item in evidence})


if __name__ == "__main__":
    unittest.main()
