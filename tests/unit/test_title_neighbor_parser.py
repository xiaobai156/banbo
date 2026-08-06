import unittest

from banbo.domain.models import Direction, Document, DocumentSource, SiteSpec
from banbo.parsers.protocol import ParserSpec
from banbo.parsers.title_neighbor import TitleNeighborParser


def doc(order, content, record_id=None):
    return Document(
        document_id=f"doc-{order}",
        source=DocumentSource.SCRIPT,
        source_url=f"https://example.test/{order}.js",
        order=order,
        content=content,
        record_id=record_id,
    )


class TitleNeighborParserTest(unittest.TestCase):
    def make_site(self):
        return SiteSpec(
            site_id="neighbor-site",
            name="邻近站",
            url="https://example.test/topic/222.html",
            direction=Direction.TOP,
            strategy="title_neighbor",
            anchors=("邻近站", "作者:"),
            keywords=("绝杀半波",),
            parser_version="1",
        )

    def make_parser(self, before=1, after=0):
        return TitleNeighborParser(
            ParserSpec(
                site_id="neighbor-site",
                strategy="title_neighbor",
                parser_version="1",
                anchors=("邻近站", "作者:"),
                keywords=("绝杀半波",),
                before_documents=before,
                after_documents=after,
                options={"window_size": 3},
            )
        )

    def test_only_parses_documents_inside_title_window(self):
        documents = (
            doc(0, "209期 绝杀半波【红单】"),
            doc(1, "209期 绝杀半波【绿双】"),
            doc(2, "邻近站 作者:123"),
        )

        evidence = self.make_parser().parse(
            self.make_site(), documents, 209
        )

        self.assertEqual(["绿双"], [item.value for item in evidence])
        self.assertEqual("title_neighbor", evidence[0].parser_name)

    def test_record_boundary_mismatch_is_exposed_to_validator(self):
        documents = (
            doc(0, "209期 绝杀半波【绿双】", record_id="other"),
            doc(1, "邻近站 作者:123", record_id="target"),
        )

        evidence = self.make_parser().parse(
            self.make_site(), documents, 209
        )

        self.assertFalse(evidence[0].same_record)

    def test_missing_title_anchor_returns_no_evidence(self):
        documents = (doc(0, "209期 绝杀半波【绿双】"),)

        evidence = self.make_parser().parse(
            self.make_site(), documents, 209
        )

        self.assertEqual((), evidence)

    def test_target_only_scope_finds_target_in_later_split_document(self):
        parser = TitleNeighborParser(
            ParserSpec(
                site_id="neighbor-site",
                strategy="title_neighbor",
                parser_version="1",
                anchors=("邻近站",),
                keywords=("绝杀半波",),
                after_documents=3,
                options={"target_only_scope": True},
            )
        )
        documents = (
            doc(0, "邻近站"),
            doc(1, "212期 绝杀半波【红单】"),
            doc(2, "210期 绝杀半波【绿双】"),
            doc(3, "211期 绝杀半波【蓝单】"),
        )

        evidence = parser.parse(self.make_site(), documents, 211)

        self.assertEqual(["蓝单"], [item.value for item in evidence])


if __name__ == "__main__":
    unittest.main()
