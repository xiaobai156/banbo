import json
import unittest

from banbo.domain.models import DocumentSource
from banbo.fetch.dynamic_source import (
    DynamicSourceError,
    DynamicSourceSpec,
    fetch_dynamic_document,
)
from banbo.fetch.http_client import FetchResponse


class FakeClient:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def fetch_text(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FetchResponse(
            requested_url=url,
            final_url=url,
            status_code=200,
            text=json.dumps(self.payloads[url], ensure_ascii=False),
        )


class DynamicDocumentSourceTest(unittest.TestCase):
    def test_selects_unique_composite_record_then_fetches_detail(self):
        list_url = "https://example.test/api/v1/users/7/references?per_page=100"
        detail_url = "https://example.test/api/v1/forums/222"
        client = FakeClient(
            {
                list_url: [
                    {
                        "id": 111,
                        "user_id": 7,
                        "draw": 211,
                        "topic": "财富榜",
                        "sub_topic": "绝杀半波",
                    },
                    {
                        "id": 222,
                        "user_id": 7,
                        "draw": 212,
                        "topic": "财富榜",
                        "sub_topic": "绝杀半波",
                    },
                    {
                        "id": 333,
                        "user_id": 8,
                        "draw": 212,
                        "topic": "财富榜",
                        "sub_topic": "绝杀半波",
                    },
                ],
                detail_url: {
                    "id": 222,
                    "user_id": 7,
                    "draw": 212,
                    "topic": "财富榜",
                    "sub_topic": "绝杀半波",
                    "content": "212期绝杀半波【红单】",
                },
            }
        )

        document = fetch_dynamic_document(
            client,
            "https://example.test/#/users/7",
            212,
            DynamicSourceSpec(
                kind="references",
                user_id="7",
                topic="财富榜",
                sub_topic="绝杀半波",
            ),
        )

        self.assertEqual(DocumentSource.API, document.source)
        self.assertEqual("222", document.record_id)
        self.assertIn("212期绝杀半波", document.content)
        self.assertEqual([list_url, detail_url], [call[0] for call in client.calls])

    def test_aggregate_bait_with_same_issue_but_wrong_topic_is_rejected(self):
        list_url = "https://example.test/api/v1/users/7/references?per_page=100"
        client = FakeClient(
            {
                list_url: [
                    {
                        "id": 111,
                        "user_id": 7,
                        "draw": 212,
                        "topic": "其它栏目",
                        "sub_topic": "绝杀半波",
                    }
                ]
            }
        )

        with self.assertRaisesRegex(DynamicSourceError, "唯一目标记录"):
            fetch_dynamic_document(
                client,
                "https://example.test/#/users/7",
                212,
                DynamicSourceSpec(
                    kind="references",
                    user_id="7",
                    topic="财富榜",
                    sub_topic="绝杀半波",
                ),
            )

    def test_duplicate_composite_records_fail_closed(self):
        list_url = "https://example.test/api/v1/users/7/forums?per_page=100"
        record = {
            "user_id": 7,
            "draw": 212,
            "topic": "绝杀半波",
        }
        client = FakeClient(
            {
                list_url: [
                    {"id": 111, **record},
                    {"id": 222, **record},
                ]
            }
        )

        with self.assertRaisesRegex(DynamicSourceError, "多个"):
            fetch_dynamic_document(
                client,
                "https://example.test/#/users/7",
                212,
                DynamicSourceSpec(
                    kind="forums",
                    user_id="7",
                    topic="绝杀半波",
                ),
            )

    def test_detail_metadata_must_match_selected_record(self):
        list_url = "https://example.test/api/v1/users/7/forums?per_page=100"
        detail_url = "https://example.test/api/v1/forums/222"
        client = FakeClient(
            {
                list_url: [
                    {
                        "id": 222,
                        "user_id": 7,
                        "draw": 212,
                        "topic": "绝杀半波",
                    }
                ],
                detail_url: {
                    "id": 999,
                    "user_id": 7,
                    "draw": 212,
                    "topic": "绝杀半波",
                    "content": "212期红单",
                },
            }
        )

        with self.assertRaisesRegex(DynamicSourceError, "ID校验失败"):
            fetch_dynamic_document(
                client,
                "https://example.test/#/users/7",
                212,
                DynamicSourceSpec(
                    kind="forums",
                    user_id="7",
                    topic="绝杀半波",
                ),
            )


if __name__ == "__main__":
    unittest.main()
