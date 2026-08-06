import unittest

from banbo.domain.models import Direction, Document, DocumentSource, SiteSpec
from banbo.parsers.nearest_document import NearestDocumentParser
from banbo.parsers.protocol import ParserSpec


def document(order, content, record_id=None):
    return Document(
        document_id=f"doc-{order}",
        source=DocumentSource.SCRIPT,
        source_url=f"https://example.test/{order}.js",
        order=order,
        content=content,
        record_id=record_id,
    )


class NearestDocumentParserTest(unittest.TestCase):
    def site(self, direction=Direction.TOP):
        return SiteSpec(
            site_id="nearest-site",
            name="最近站",
            url="https://example.test/topic/1.html",
            direction=direction,
            strategy="nearest_document",
            anchors=("最近站", "绝杀半波"),
            keywords=("半波",),
            parser_version="1",
        )

    def parser(self, before=2, after=2, **options):
        return NearestDocumentParser(
            ParserSpec(
                site_id="nearest-site",
                strategy="nearest_document",
                parser_version="1",
                anchors=("最近站", "绝杀半波"),
                keywords=("半波",),
                before_documents=before,
                after_documents=after,
                value_pattern=r"(?P<value>[红绿蓝]\s*(?:波\s*)?[单双])",
                options=options,
            )
        )

    def test_selects_nearest_target_document_not_first_in_window(self):
        documents = (
            document(0, "211期绝杀半波【红单】"),
            document(1, "最近站 211期【绝杀半波】"),
            document(2, "211期绝杀半波【绿双】"),
            document(3, "211期绝杀半波【蓝单】"),
        )

        evidence = self.parser(before=1, after=2).parse(
            self.site(), documents, 211
        )

        self.assertEqual({"红单", "绿双"}, {item.value for item in evidence})
        self.assertTrue(all(item.candidate_count == 2 for item in evidence))
        self.assertTrue(
            all(item.document_relation == "declared_nearest_document" for item in evidence)
        )

    def test_side_option_restricts_nearest_search(self):
        documents = (
            document(0, "211期绝杀半波【红单】"),
            document(1, "最近站 211期【绝杀半波】"),
            document(2, "211期绝杀半波【绿双】"),
        )

        evidence = self.parser(
            before=1,
            after=1,
            candidate_side="after",
        ).parse(self.site(), documents, 211)

        self.assertEqual(["绿双"], [item.value for item in evidence])

    def test_requires_target_issue_in_anchor_when_configured(self):
        documents = (
            document(0, "最近站 210期【绝杀半波】"),
            document(1, "211期绝杀半波【绿双】"),
        )

        evidence = self.parser(
            require_target_in_anchor=True,
        ).parse(self.site(), documents, 211)

        self.assertEqual((), evidence)

    def test_record_mismatch_is_preserved_for_validation(self):
        documents = (
            document(0, "最近站 211期【绝杀半波】", "title"),
            document(1, "211期绝杀半波【绿双】", "other"),
        )

        evidence = self.parser(before=0, after=1).parse(
            self.site(), documents, 211
        )

        self.assertFalse(evidence[0].same_record)

    def test_top_direction_does_not_use_fourth_anchor_document(self):
        documents = tuple(
            document(index, f"最近站 211期绝杀半波【{value}】")
            for index, value in enumerate(("红单", "红双", "绿单", "蓝双"))
        )

        evidence = self.parser(before=0, after=0).parse(
            self.site(), documents, 211
        )

        self.assertEqual({"红单", "红双", "绿单"}, {item.value for item in evidence})


if __name__ == "__main__":
    unittest.main()
