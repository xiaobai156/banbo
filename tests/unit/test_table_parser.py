import unittest

from banbo.domain.models import Direction, Document, DocumentSource, SiteSpec
from banbo.parsers.protocol import ParserSpec
from banbo.parsers.table import TableParser


class TableParserTest(unittest.TestCase):
    def setUp(self):
        self.site = SiteSpec(
            site_id="table-site",
            name="表格站",
            url="https://example.test/table",
            direction=Direction.TOP,
            strategy="table",
            anchors=("表格站", "综合绝杀"),
            keywords=("绝杀半波",),
            parser_version="1",
        )
        self.parser = TableParser(
            ParserSpec(
                site_id="table-site",
                strategy="table",
                parser_version="1",
                anchors=("表格站", "综合绝杀"),
                keywords=("绝杀半波",),
                options={"window_size": 3},
            )
        )

    def document(self, content):
        return Document(
            document_id="table-doc",
            source=DocumentSource.PAGE,
            source_url="https://example.test/table",
            order=0,
            content=content,
        )

    def test_extracts_issue_and_value_from_same_table_row(self):
        content = (
            "<h2>表格站 综合绝杀</h2><table>"
            "<tr><td>209期</td><td>绝杀半波</td><td>绿双</td></tr>"
            "<tr><td>208期</td><td>绝杀半波</td><td>红单</td></tr>"
            "</table>"
        )

        evidence = self.parser.parse(
            self.site, (self.document(content),), 209
        )

        self.assertEqual(["绿双"], [item.value for item in evidence])

    def test_does_not_join_issue_and_value_across_rows(self):
        content = (
            "<h2>表格站 综合绝杀</h2><table>"
            "<tr><td>209期</td><td>绝杀半波</td></tr>"
            "<tr><td>208期</td><td>绿双</td></tr>"
            "</table>"
        )

        evidence = self.parser.parse(
            self.site, (self.document(content),), 209
        )

        self.assertEqual((), evidence)

    def test_same_issue_conflict_is_preserved(self):
        content = (
            "<h2>表格站 综合绝杀</h2><table>"
            "<tr><td>209期</td><td>绝杀半波</td><td>绿双</td></tr>"
            "<tr><td>209期</td><td>绝杀半波</td><td>红单</td></tr>"
            "</table>"
        )

        evidence = self.parser.parse(
            self.site, (self.document(content),), 209
        )

        self.assertEqual({"绿双", "红单"}, {item.value for item in evidence})

    def test_target_only_scope_ignores_boundary_order(self):
        parser = TableParser(
            ParserSpec(
                site_id="table-site",
                strategy="table",
                parser_version="1",
                anchors=("表格站", "综合绝杀"),
                keywords=("绝杀半波",),
                options={"window_size": 3, "target_only_scope": True},
            )
        )
        content = (
            "<h2>表格站 综合绝杀</h2><table>"
            "<tr><td>208期</td><td>绝杀半波</td><td>红单</td></tr>"
            "<tr><td>207期</td><td>绝杀半波</td><td>蓝双</td></tr>"
            "<tr><td>209期</td><td>绝杀半波</td><td>绿双</td></tr>"
            "</table>"
        )

        evidence = parser.parse(
            self.site, (self.document(content),), 209
        )

        self.assertEqual(["绿双"], [item.value for item in evidence])


if __name__ == "__main__":
    unittest.main()
