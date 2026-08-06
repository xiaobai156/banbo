import unittest

from banbo.domain.models import Direction, Document, DocumentSource, SiteSpec
from banbo.parsers.history_block import HistoryBlockParser
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


def site(direction=Direction.TOP):
    return SiteSpec(
        site_id="target-site",
        name="目标站",
        url="https://example.test/topic/222.html",
        direction=direction,
        strategy="history_block",
        anchors=("目标站", "绝杀半波"),
        parser_version="1",
        keywords=("绝杀半波",),
    )


class HistoryBlockParserTest(unittest.TestCase):
    def parser(self, **options):
        return HistoryBlockParser(
            ParserSpec(
                site_id="target-site",
                strategy="history_block",
                parser_version="1",
                anchors=("目标站", "绝杀半波"),
                keywords=("绝杀半波",),
                options=options,
            )
        )

    def test_ignores_same_issue_bait_outside_site_anchor(self):
        documents = (
            document(0, "其它栏目 209期 绝杀半波【红单】"),
            document(1, "目标站 绝杀半波\n209期 绝杀半波【绿双】"),
        )

        evidence = self.parser().parse(site(), documents, 209)

        self.assertEqual(["绿双"], [item.value for item in evidence])
        self.assertEqual("doc-1", evidence[0].document_id)

    def test_same_period_conflict_is_preserved_for_validation_gate(self):
        documents = (
            document(
                0,
                "目标站 绝杀半波\n"
                "209期 绝杀半波【绿双】\n"
                "209期 绝杀半波【红单】",
            ),
        )

        evidence = self.parser(window_size=5).parse(site(), documents, 209)

        self.assertEqual({"绿双", "红单"}, {item.value for item in evidence})
        self.assertTrue(all(item.candidate_count == 2 for item in evidence))

    def test_unknown_open_result_does_not_hide_same_period_conflict(self):
        documents = (
            document(
                0,
                "目标站 绝杀半波\n"
                "209期 绝杀半波【绿双】开0000\n"
                "209期 绝杀半波【红单】开马49",
            ),
        )

        evidence = self.parser().parse(site(), documents, 209)

        self.assertEqual({"绿双", "红单"}, {item.value for item in evidence})

    def test_does_not_borrow_value_from_next_issue(self):
        documents = (
            document(
                0,
                "目标站 绝杀半波\n"
                "209期 绝杀半波 开奖待定\n"
                "208期 绝杀半波【蓝单】",
            ),
        )

        evidence = self.parser().parse(site(), documents, 209)

        self.assertEqual((), evidence)

    def test_top_and_bottom_windows_use_raw_candidate_order(self):
        content = (
            "目标站 绝杀半波\n"
            "206期 绝杀半波【红单】\n"
            "207期 绝杀半波【红双】\n"
            "208期 绝杀半波【绿单】\n"
            "209期 绝杀半波【绿双】"
        )

        top_evidence = self.parser(window_size=3).parse(
            site(Direction.TOP), (document(0, content),), 209
        )
        bottom_evidence = self.parser(window_size=3).parse(
            site(Direction.BOTTOM), (document(0, content),), 209
        )

        self.assertEqual((), top_evidence)
        self.assertEqual(["绿双"], [item.value for item in bottom_evidence])

    def test_duplicate_same_issue_does_not_consume_direction_group(self):
        content = (
            "目标站 绝杀半波\n"
            "209期 绝杀半波【红单】\n"
            "209期 绝杀半波【红单】\n"
            "208期 绝杀半波【红双】\n"
            "207期 绝杀半波【绿单】\n"
            "206期 绝杀半波【蓝双】"
        )

        evidence = self.parser().parse(
            site(Direction.TOP), (document(0, content),), 207
        )

        self.assertEqual(["绿单"], [item.value for item in evidence])
        self.assertEqual((209, 208, 207), evidence[0].boundary_issues)

    def test_target_only_scope_ignores_other_issue_boundary(self):
        content = (
            "目标站 绝杀半波\n"
            "212期 绝杀半波【红单】\n"
            "211期 绝杀半波【绿双】\n"
            "210期 绝杀半波【蓝单】"
        )

        evidence = self.parser(
            window_size=1,
            target_only_scope=True,
        ).parse(site(Direction.TOP), (document(0, content),), 211)

        self.assertEqual(["绿双"], [item.value for item in evidence])


if __name__ == "__main__":
    unittest.main()
