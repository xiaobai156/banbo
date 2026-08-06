import json
import unittest
from pathlib import Path

from banbo.domain.models import Direction
from banbo.parsers.specs import ParserSpecError, parse_parser_specs


def valid_payload():
    return {
        "schema_version": 1,
        "specs": [
            {
                "site_id": "hw-0001",
                "parser_id": "hw-0001:history_block:v1",
                "strategy": "history_block",
                "direction": "top",
                "anchors": ["站点"],
                "keywords": ["绝杀半波"],
                "issue_pattern": r"(?P<issue>\d{1,4})期",
                "value_pattern": r"(?P<value>[红绿蓝](?:波)?[单双])",
                "before_documents": 0,
                "after_documents": 0,
                "target_only": True,
                "record_id_pattern": None,
                "topic_id_pattern": r"/topic/(?P<topic_id>\d+)\.html",
                "parser_version": "1",
                "options": {"window_size": 3},
            }
        ],
    }


class ParserSpecsTest(unittest.TestCase):
    def test_repaired_sites_use_stable_section_anchors_only(self):
        config_path = (
            Path(__file__).resolve().parents[2]
            / "config"
            / "parser_specs.json"
        )
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        specs = {
            item["site_id"]: item
            for item in payload["specs"]
            if item["site_id"] in {"hw-0045", "hw-0046", "hw-0053"}
        }

        self.assertEqual(["杀料榜"], specs["hw-0045"]["anchors"])
        self.assertEqual(
            ["杀料榜", "稳杀半波"],
            specs["hw-0046"]["anchors"],
        )
        self.assertEqual(["杀料贴"], specs["hw-0053"]["anchors"])
        for spec in specs.values():
            self.assertTrue(all("http" not in anchor for anchor in spec["anchors"]))
            self.assertTrue(all(".com" not in anchor for anchor in spec["anchors"]))

    def test_parses_strict_parser_spec(self):
        spec = parse_parser_specs(valid_payload())[0]

        self.assertEqual("hw-0001", spec.site_id)
        self.assertEqual("hw-0001:history_block:v1", spec.parser_id)
        self.assertEqual(Direction.TOP, spec.direction)
        self.assertEqual(("站点",), spec.anchors)

    def test_duplicate_site_id_is_rejected(self):
        payload = valid_payload()
        payload["specs"].append(dict(payload["specs"][0]))

        with self.assertRaisesRegex(ParserSpecError, "重复"):
            parse_parser_specs(payload)

    def test_duplicate_parser_id_is_rejected(self):
        payload = valid_payload()
        duplicate = dict(payload["specs"][0])
        duplicate["site_id"] = "hw-0002"
        payload["specs"].append(duplicate)

        with self.assertRaisesRegex(ParserSpecError, "parser_id重复"):
            parse_parser_specs(payload)

    def test_invalid_regex_is_rejected(self):
        payload = valid_payload()
        payload["specs"][0]["issue_pattern"] = "("

        with self.assertRaisesRegex(ParserSpecError, "正则"):
            parse_parser_specs(payload)

    def test_empty_anchor_is_rejected(self):
        payload = valid_payload()
        payload["specs"][0]["anchors"] = []

        with self.assertRaisesRegex(ParserSpecError, "anchors"):
            parse_parser_specs(payload)

    def test_direction_window_bypass_is_rejected(self):
        payload = valid_payload()
        payload["specs"][0]["options"]["target_only_scope"] = True

        with self.assertRaisesRegex(ParserSpecError, "target_only_scope"):
            parse_parser_specs(payload)

    def test_non_three_direction_window_is_rejected(self):
        payload = valid_payload()
        payload["specs"][0]["options"]["window_size"] = 5

        with self.assertRaisesRegex(ParserSpecError, "window_size"):
            parse_parser_specs(payload)

    def test_record_id_pattern_requires_capture_group(self):
        payload = valid_payload()
        payload["specs"][0]["topic_id_pattern"] = r"/topic/\d+\.html"

        with self.assertRaisesRegex(ParserSpecError, "捕获组"):
            parse_parser_specs(payload)

    def test_dynamic_api_requires_structured_source_definition(self):
        payload = valid_payload()
        payload["specs"][0]["strategy"] = "dynamic_api"
        payload["specs"][0]["options"] = {}

        with self.assertRaisesRegex(ParserSpecError, "动态来源"):
            parse_parser_specs(payload)

    def test_article_list_source_requires_exact_title_and_bounded_pagination(self):
        payload = valid_payload()
        payload["specs"][0]["options"] = {
            "window_size": 3,
            "source": {
                "kind": "article_list",
                "title_anchor": "绿树成荫",
                "title_suffix": "【绝杀半波】",
                "next_text": "下一页",
                "max_pages": 9,
            },
        }

        spec = parse_parser_specs(payload)[0]

        self.assertEqual(
            "article_list",
            spec.options["source"]["kind"],
        )

    def test_article_list_source_rejects_unbounded_page_count(self):
        payload = valid_payload()
        payload["specs"][0]["options"] = {
            "source": {
                "kind": "article_list",
                "title_anchor": "绿树成荫",
                "title_suffix": "【绝杀半波】",
                "next_text": "下一页",
                "max_pages": 10,
            }
        }

        with self.assertRaisesRegex(ParserSpecError, "max_pages"):
            parse_parser_specs(payload)


if __name__ == "__main__":
    unittest.main()
