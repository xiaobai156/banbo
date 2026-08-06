from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from banbo.domain.normalization import normalize_text

from .http_client import FetchResponse


class ArticleListResolutionError(RuntimeError):
    """The requested issue/title cannot be uniquely resolved from the list."""


@dataclass(frozen=True)
class ArticleListSpec:
    title_anchor: str
    title_suffix: str = "【绝杀半波】"
    next_text: str = "下一页"
    max_pages: int = 9

    def __post_init__(self) -> None:
        if not self.title_anchor.strip():
            raise ValueError("列表文章标题锚点不能为空")
        if not self.title_suffix.strip():
            raise ValueError("列表文章标题后缀不能为空")
        if not self.next_text.strip():
            raise ValueError("列表下一页文本不能为空")
        if not 1 <= self.max_pages <= 9:
            raise ValueError("列表最大翻页数必须在1到9之间")


@dataclass(frozen=True)
class ResolvedArticle:
    article_url: str
    title: str
    list_pages: tuple[str, ...]


@dataclass(frozen=True)
class _Link:
    href: str
    text: str


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[_Link] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() != "a" or self._href is not None:
            return
        attributes = {str(key).casefold(): value for key, value in attrs}
        href = attributes.get("href")
        if href:
            self._href = str(href).strip()
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._href is None:
            return
        self.links.append(_Link(self._href, "".join(self._text)))
        self._href = None
        self._text = []


def _origin(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    return parsed.scheme.casefold(), parsed.netloc.casefold()


def _title_key(value: str) -> str:
    normalized = normalize_text(value)
    return re.sub(r"[\s:：]", "", normalized)


def _same_origin_url(base_url: str, href: str) -> str | None:
    resolved = urljoin(base_url, href)
    parsed = urlparse(resolved)
    if parsed.scheme.casefold() not in {"http", "https"}:
        return None
    if _origin(resolved) != _origin(base_url):
        return None
    return resolved


def _parse_links(response: FetchResponse) -> tuple[_Link, ...]:
    parser = _LinkParser()
    parser.feed(response.text)
    parser.close()
    return tuple(parser.links)


def resolve_article_from_list(
    client,
    list_url: str,
    target_issue: int,
    spec: ArticleListSpec,
) -> ResolvedArticle:
    """Resolve one exact issue/title link by following the page's next links."""

    if target_issue <= 0:
        raise ValueError("目标期数必须是正整数")
    target_key = _title_key(
        f"{target_issue}期{spec.title_anchor}{spec.title_suffix}"
    )
    next_key = _title_key(spec.next_text)
    current_url = list_url
    visited: set[str] = set()
    pages: list[str] = []

    for page_number in range(spec.max_pages):
        if current_url in visited:
            raise ArticleListResolutionError("列表翻页出现循环")
        required_origin = None if not pages else pages[-1]
        response = client.fetch_text(
            current_url,
            required_origin=required_origin,
        )
        page_url = response.final_url
        if page_url in visited:
            raise ArticleListResolutionError("列表页面跳转出现循环")
        visited.add(page_url)
        pages.append(page_url)

        links = _parse_links(response)
        article_candidates: dict[str, _Link] = {}
        for link in links:
            if not _title_key(link.text).startswith(target_key):
                continue
            article_url = _same_origin_url(page_url, link.href)
            if article_url is not None:
                article_candidates.setdefault(article_url, link)

        if len(article_candidates) > 1:
            raise ArticleListResolutionError(
                f"第{target_issue}期精确文章存在多个候选"
            )
        if article_candidates:
            article_url, link = next(iter(article_candidates.items()))
            return ResolvedArticle(
                article_url=article_url,
                title=normalize_text(link.text),
                list_pages=tuple(pages),
            )

        next_candidates: dict[str, _Link] = {}
        for link in links:
            if next_key not in _title_key(link.text):
                continue
            next_url = _same_origin_url(page_url, link.href)
            if next_url is not None:
                next_candidates.setdefault(next_url, link)
        if len(next_candidates) > 1:
            raise ArticleListResolutionError("列表存在多个下一页候选")
        if not next_candidates:
            break
        current_url = next(iter(next_candidates))

    raise ArticleListResolutionError(
        f"翻完{len(pages)}页仍未找到{target_issue}期专属文章"
    )
