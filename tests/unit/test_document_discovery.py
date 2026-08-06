import unittest

from banbo.domain.models import DocumentSource
from banbo.fetch.document_discovery import (
    DiscoveryOptions,
    DocumentDiscoverer,
    DocumentRequest,
)
from banbo.fetch.http_client import FetchResponse


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def fetch_text(self, url, **kwargs):
        self.calls.append(url)
        return FetchResponse(
            requested_url=url,
            final_url=url,
            status_code=200,
            text=self.responses[url],
        )


class FakeBrowserClient:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def fetch_text(self, url):
        self.calls.append(url)
        return FetchResponse(
            requested_url=url,
            final_url=url,
            status_code=200,
            text=self.text,
        )


class DocumentDiscoveryTest(unittest.TestCase):
    def test_discovers_page_inline_script_external_script_and_iframe(self):
        page_url = "https://example.test/topic/1.html"
        script_url = "https://example.test/assets/data.js"
        iframe_url = "https://example.test/frame/body.html"
        client = FakeClient(
            {
                page_url: (
                    "<html><body>正文</body>"
                    "<script>window.data='206期 绿双'</script>"
                    '<script src="/assets/data.js"></script>'
                    '<iframe src="/frame/body.html"></iframe>'
                    "</html>"
                ),
                script_url: "window.more='205期 绿单'",
                iframe_url: "<p>204期 红单</p>",
            }
        )
        discoverer = DocumentDiscoverer(client)

        documents = discoverer.discover(
            page_url,
            options=DiscoveryOptions(fetch_scripts=True, fetch_iframes=True),
        )

        self.assertEqual(
            [
                DocumentSource.PAGE,
                DocumentSource.SCRIPT,
                DocumentSource.SCRIPT,
                DocumentSource.IFRAME,
            ],
            [document.source for document in documents],
        )
        self.assertEqual(3, len(client.calls))
        self.assertIn("206期 绿双", documents[1].content)
        self.assertIn("205期 绿单", documents[2].content)
        self.assertIn("204期 红单", documents[3].content)

    def test_detail_url_id_is_attached_only_to_matching_source_url(self):
        page_url = "https://example.test/topic/222.html"
        script_url = "https://example.test/assets/data.js"
        client = FakeClient(
            {
                page_url: "<script src='/assets/data.js'></script>",
                script_url: "222期 绝杀半波【绿双】",
            }
        )

        documents = DocumentDiscoverer(client).discover(
            page_url,
            record_id_pattern=r"/topic/(?P<topic_id>\d+)\.html",
        )

        self.assertEqual("222", documents[0].record_id)
        self.assertIsNone(documents[1].record_id)

    def test_declared_record_pattern_fails_when_entry_id_is_missing(self):
        page_url = "https://example.test/topic/222.html"
        client = FakeClient({page_url: "<html></html>"})

        with self.assertRaisesRegex(RuntimeError, "未找到专属记录ID"):
            DocumentDiscoverer(client).discover(
                page_url,
                record_id_pattern=r"/detail/(?P<record_id>\d+)\.html",
            )

    def test_deduplicates_repeated_external_documents(self):
        page_url = "https://example.test/topic/1.html"
        script_url = "https://example.test/assets/data.js"
        client = FakeClient(
            {
                page_url: (
                    '<script src="/assets/data.js"></script>'
                    '<script src="/assets/data.js"></script>'
                ),
                script_url: "same",
            }
        )

        documents = DocumentDiscoverer(client).discover(page_url)

        self.assertEqual(2, len(documents))
        self.assertEqual([page_url, script_url], client.calls)

    def test_does_not_follow_cross_origin_embeds_by_default(self):
        page_url = "https://example.test/topic/1.html"
        client = FakeClient(
            {
                page_url: (
                    '<script src="https://other.test/data.js"></script>'
                    '<iframe src="https://other.test/frame.html"></iframe>'
                )
            }
        )

        documents = DocumentDiscoverer(client).discover(page_url)

        self.assertEqual(1, len(documents))
        self.assertEqual([page_url], client.calls)

    def test_adds_explicit_api_and_browser_documents(self):
        page_url = "https://example.test/topic/1.html"
        api_url = "https://example.test/api/articles/1"
        client = FakeClient(
            {
                page_url: "<html></html>",
                api_url: '{"id": 1, "content": "209期绿双"}',
            }
        )
        browser = FakeBrowserClient("<body>浏览器正文</body>")
        discoverer = DocumentDiscoverer(client, browser_client=browser)

        documents = discoverer.discover(
            page_url,
            options=DiscoveryOptions(
                additional_requests=(
                    DocumentRequest(DocumentSource.API, api_url, "1"),
                ),
                render_browser=True,
            ),
        )

        self.assertEqual(
            [DocumentSource.PAGE, DocumentSource.API, DocumentSource.BROWSER],
            [document.source for document in documents],
        )
        self.assertEqual("1", documents[1].record_id)
        self.assertEqual([page_url], browser.calls)

    def test_deduplicates_equal_content_from_different_embed_urls(self):
        page_url = "https://example.test/topic/1.html"
        first_url = "https://example.test/a.js"
        second_url = "https://example.test/b.js"
        client = FakeClient(
            {
                page_url: (
                    '<script src="/a.js"></script>'
                    '<script src="/b.js"></script>'
                ),
                first_url: "same payload",
                second_url: "same payload",
            }
        )

        documents = DocumentDiscoverer(client).discover(page_url)

        self.assertEqual(2, len(documents))
        self.assertEqual([page_url, first_url, second_url], client.calls)

    def test_allows_configured_external_data_script_and_decodes_payload(self):
        page_url = "https://example.test/topic/1.html"
        script_url = "https://xia06.cosds.ahsccn.com/upload/script/data.js"
        client = FakeClient(
            {
                page_url: f'<script src="{script_url}"></script>',
                script_url: (
                    'document.writeln(strdecode("MjEw5pyf44CQ57u/5Y+M44CR"));'
                ),
            }
        )

        documents = DocumentDiscoverer(client).discover(
            page_url,
            options=DiscoveryOptions(
                allowed_external_hosts=("xia06.cosds.ahsccn.com",),
                script_path_markers=("/upload/script/",),
            ),
        )

        self.assertEqual(3, len(documents))
        self.assertEqual(DocumentSource.SCRIPT, documents[1].source)
        self.assertEqual("210期【绿双】", documents[2].content)

    def test_decodes_javascript_unicode_escape_as_separate_document(self):
        page_url = "https://example.test/topic/1.html"
        client = FakeClient(
            {
                page_url: (
                    "<script>window.value='\\u0032\\u0031\\u0030"
                    "\\u671f\\u7eff\\u5355'</script>"
                )
            }
        )

        documents = DocumentDiscoverer(client).discover(page_url)

        self.assertTrue(
            any(
                "210期绿单" in document.content
                and "\\u671f" not in document.content
                for document in documents
            )
        )


if __name__ == "__main__":
    unittest.main()
