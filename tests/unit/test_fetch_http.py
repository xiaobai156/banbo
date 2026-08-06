import unittest

from banbo.fetch.http_client import FetchError, HttpClient, RawResponse


class RecordingTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, url, *, timeout, verify_ssl, headers):
        self.calls.append(
            {
                "url": url,
                "timeout": timeout,
                "verify_ssl": verify_ssl,
                "headers": headers,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        return None


class HttpClientTest(unittest.TestCase):
    def test_same_url_is_downloaded_once_per_client(self):
        transport = RecordingTransport(
            [RawResponse("https://example.test/a", 200, b"hello", "utf-8")]
        )
        client = HttpClient(transport=transport, retries=0)

        first = client.fetch_text("https://example.test/a")
        second = client.fetch_text("https://example.test/a")

        self.assertEqual("hello", first.text)
        self.assertIs(first, second)
        self.assertEqual(1, len(transport.calls))

    def test_proxy_fake_ip_is_not_rejected_by_address_classification(self):
        url = "https://[fd00::1234]/topic/1.html"
        transport = RecordingTransport([RawResponse(url, 200, b"ok", "utf-8")])
        client = HttpClient(transport=transport, retries=0)

        response = client.fetch_text(url)

        self.assertEqual("ok", response.text)
        self.assertEqual(url, transport.calls[0]["url"])

    def test_retries_transient_transport_error(self):
        transport = RecordingTransport(
            [
                TimeoutError("slow"),
                RawResponse("https://example.test/a", 200, b"ok", "utf-8"),
            ]
        )
        client = HttpClient(transport=transport, retries=1, retry_delay=0)

        response = client.fetch_text("https://example.test/a")

        self.assertEqual("ok", response.text)
        self.assertEqual(2, len(transport.calls))

    def test_rejects_oversized_response(self):
        transport = RecordingTransport(
            [RawResponse("https://example.test/a", 200, b"12345", "utf-8")]
        )
        client = HttpClient(transport=transport, retries=0, max_response_bytes=4)

        with self.assertRaises(FetchError):
            client.fetch_text("https://example.test/a")

    def test_rejects_cross_origin_redirect(self):
        transport = RecordingTransport(
            [RawResponse("https://other.test/a", 200, b"ok", "utf-8")]
        )
        client = HttpClient(transport=transport, retries=0)

        with self.assertRaisesRegex(FetchError, "其它源"):
            client.fetch_text("https://example.test/a")

    def test_prefers_valid_utf8_when_server_reports_latin1(self):
        url = "https://example.test/a"
        transport = RecordingTransport(
            [RawResponse(url, 200, "绝杀半波".encode("utf-8"), "ISO-8859-1")]
        )
        client = HttpClient(transport=transport, retries=0)

        response = client.fetch_text(url)

        self.assertEqual("绝杀半波", response.text)

    def test_falls_back_to_reported_encoding_for_non_utf8_bytes(self):
        url = "https://example.test/a"
        transport = RecordingTransport(
            [RawResponse(url, 200, "绝杀半波".encode("gb18030"), "gb18030")]
        )
        client = HttpClient(transport=transport, retries=0)

        response = client.fetch_text(url)

        self.assertEqual("绝杀半波", response.text)


if __name__ == "__main__":
    unittest.main()
