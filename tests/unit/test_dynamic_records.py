import unittest

from banbo.fetch.dynamic_records import (
    RecordBoundaryError,
    RecordBoundarySpec,
    extract_record_id,
    resolve_unique_record,
)


class DynamicRecordBoundaryTest(unittest.TestCase):
    def test_extracts_record_id_from_supported_detail_urls(self):
        cases = {
            "https://example.test/article/admin/15341640": "15341640",
            "https://example.test/article/manager/8161.html": "8161",
            "https://example.test/users/11993/references/15341640": "15341640",
            "https://example.test/topic/732152.html": "732152",
            "https://example.test/gsb.aspx?id=029": "029",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(expected, extract_record_id(url))

    def test_named_pattern_is_strict_and_does_not_fall_back(self):
        self.assertEqual(
            "222",
            extract_record_id(
                "https://example.test/detail/222.html",
                r"/detail/(?P<record_id>\d+)\.html",
            ),
        )
        self.assertIsNone(
            extract_record_id(
                "https://example.test/topic/222.html",
                r"/detail/(?P<record_id>\d+)\.html",
            )
        )

    def test_resolves_only_the_url_record_from_nested_aggregate_payload(self):
        payload = {
            "data": {
                "items": [
                    {
                        "id": 111,
                        "author": "诱饵",
                        "title": "209期绝杀半波",
                        "content": "209期【红单】",
                    },
                    {
                        "id": 222,
                        "author": "目标作者",
                        "title": "209期绝杀半波",
                        "content": "209期【绿双】",
                    },
                ]
            }
        }

        resolved = resolve_unique_record(
            payload,
            RecordBoundarySpec(
                record_id="222",
                expected_author="目标作者",
                expected_title_contains=("绝杀半波",),
            ),
        )

        self.assertEqual(("data", "items", 1), resolved.path)
        self.assertEqual("209期【绿双】", resolved.record["content"])

    def test_duplicate_same_id_fails_closed(self):
        payload = {
            "items": [
                {"id": 222, "content": "209期【绿双】"},
                {"id": "222", "content": "209期【红单】"},
            ]
        }

        with self.assertRaisesRegex(RecordBoundaryError, "多个同ID"):
            resolve_unique_record(payload, RecordBoundarySpec(record_id="222"))

    def test_missing_id_fails_closed_even_when_issue_and_keyword_match(self):
        payload = {
            "items": [
                {
                    "id": 111,
                    "title": "209期绝杀半波",
                    "content": "209期【绿双】",
                }
            ]
        }

        with self.assertRaisesRegex(RecordBoundaryError, "未找到URL记录ID"):
            resolve_unique_record(payload, RecordBoundarySpec(record_id="222"))

    def test_metadata_mismatch_fails_after_id_match(self):
        payload = {
            "items": [
                {
                    "id": 222,
                    "author": "其他作者",
                    "title": "209期绝杀半波",
                    "column": "其它栏目",
                    "content": "209期【绿双】",
                }
            ]
        }

        with self.assertRaisesRegex(RecordBoundaryError, "作者校验失败"):
            resolve_unique_record(
                payload,
                RecordBoundarySpec(
                    record_id="222",
                    expected_author="目标作者",
                    expected_title_contains=("绝杀半波",),
                    expected_column="半波",
                ),
            )


if __name__ == "__main__":
    unittest.main()
