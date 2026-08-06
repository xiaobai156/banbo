import unittest

from banbo.fetch.article_list import (
    ArticleListResolutionError,
    ArticleListSpec,
    resolve_article_from_list,
)
from banbo.fetch.http_client import FetchResponse


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def fetch_text(self, url, **kwargs):
        self.calls.append((url, kwargs))
        try:
            text = self.pages[url]
        except KeyError as exc:
            raise AssertionError(f"意外请求：{url}") from exc
        return FetchResponse(
            requested_url=url,
            final_url=url,
            status_code=200,
            text=text,
        )


def link(href, title):
    return f'<a href="{href}">{title}</a>'


class ArticleListDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.list_url = "https://list.example/list.aspx?id=79&page=1"
        self.spec = ArticleListSpec(
            title_anchor="绿树成荫",
            title_suffix="【绝杀半波】",
            max_pages=9,
        )

    def test_follows_actual_next_link_until_exact_target_is_found(self):
        page_two = "https://list.example/list.aspx?id=79&page=2"
        client = FakeClient(
            {
                self.list_url: (
                    link("?id=1", "218期：其他站【绝杀半波】")
                    + link("?id=79&page=2", "下一页")
                ),
                page_two: link(
                    "/article.aspx?id=972334",
                    "218期:绿树成荫【绝杀半波】已免费公开",
                ),
            }
        )

        resolved = resolve_article_from_list(
            client,
            self.list_url,
            218,
            self.spec,
        )

        self.assertEqual(
            "https://list.example/article.aspx?id=972334",
            resolved.article_url,
        )
        self.assertEqual([self.list_url, page_two], [call[0] for call in client.calls])
        self.assertEqual(self.list_url, client.calls[1][1]["required_origin"])

    def test_does_not_guess_a_page_when_next_link_is_missing(self):
        client = FakeClient({self.list_url: "没有目标文章"})

        with self.assertRaisesRegex(ArticleListResolutionError, "未找到"):
            resolve_article_from_list(
                client,
                self.list_url,
                218,
                self.spec,
            )

        self.assertEqual([self.list_url], [call[0] for call in client.calls])

    def test_multiple_exact_articles_fail_closed(self):
        client = FakeClient(
            {
                self.list_url: (
                    link("/article.aspx?id=1", "218期:绿树成荫【绝杀半波】")
                    + link("/article.aspx?id=2", "218期:绿树成荫【绝杀半波】")
                )
            }
        )

        with self.assertRaisesRegex(ArticleListResolutionError, "多个"):
            resolve_article_from_list(
                client,
                self.list_url,
                218,
                self.spec,
            )

    def test_next_page_cycle_is_rejected(self):
        page_two = "https://list.example/list.aspx?id=79&page=2"
        client = FakeClient(
            {
                self.list_url: link("?id=79&page=2", "下一页"),
                page_two: link("?id=79&page=2", "下一页"),
            }
        )

        with self.assertRaisesRegex(ArticleListResolutionError, "循环"):
            resolve_article_from_list(
                client,
                self.list_url,
                218,
                self.spec,
            )


if __name__ == "__main__":
    unittest.main()
