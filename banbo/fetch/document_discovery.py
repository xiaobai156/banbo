from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from banbo.domain.models import Document, DocumentSource

from .decoding import decode_embedded_text
from .dynamic_records import RecordBoundaryError, extract_record_id
from .http_client import HttpClient


@dataclass(frozen=True)
class DiscoveryOptions:
    fetch_scripts: bool = True
    fetch_iframes: bool = True
    allow_cross_origin: bool = False
    additional_requests: tuple["DocumentRequest", ...] = ()
    render_browser: bool = False
    allowed_external_hosts: tuple[str, ...] = ()
    script_path_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentRequest:
    source: DocumentSource
    url: str
    record_id: str | None = None


@dataclass(frozen=True)
class _EmbeddedReference:
    source: DocumentSource
    value: str
    inline: bool


class _ReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[_EmbeddedReference] = []
        self._inline_script_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = {str(key).lower(): value for key, value in attrs}
        lowered = tag.lower()
        if lowered == "script":
            source = attributes.get("src")
            if source:
                self.references.append(
                    _EmbeddedReference(DocumentSource.SCRIPT, str(source), False)
                )
            else:
                self._inline_script_parts = []
        elif lowered == "iframe" and attributes.get("src"):
            self.references.append(
                _EmbeddedReference(
                    DocumentSource.IFRAME,
                    str(attributes["src"]),
                    False,
                )
            )

    def handle_data(self, data: str) -> None:
        if self._inline_script_parts is not None:
            self._inline_script_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or self._inline_script_parts is None:
            return
        content = "".join(self._inline_script_parts).strip()
        if content:
            self.references.append(
                _EmbeddedReference(DocumentSource.SCRIPT, content, True)
            )
        self._inline_script_parts = None


def _same_origin(left: str, right: str) -> bool:
    left_url = urlparse(left)
    right_url = urlparse(right)
    return (
        left_url.scheme.lower(),
        left_url.netloc.lower(),
    ) == (
        right_url.scheme.lower(),
        right_url.netloc.lower(),
    )


def _document_id(source: DocumentSource, source_url: str, content: str) -> str:
    digest = hashlib.sha256(
        f"{source.value}\0{source_url}\0{content}".encode(
            "utf-8", errors="replace"
        )
    ).hexdigest()[:20]
    return f"{source.value}:{digest}"


class DocumentDiscoverer:
    def __init__(self, client: HttpClient, *, browser_client=None) -> None:
        self._client = client
        self._browser_client = browser_client

    def discover(
        self,
        entry_url: str,
        *,
        options: DiscoveryOptions | None = None,
        record_id_pattern: str | None = None,
    ) -> tuple[Document, ...]:
        options = options or DiscoveryOptions()
        page = self._client.fetch_text(entry_url)
        entry_record_id = (
            None
            if record_id_pattern is None
            else extract_record_id(entry_url, record_id_pattern)
        )
        if record_id_pattern is not None and entry_record_id is None:
            raise RecordBoundaryError("入口URL未找到专属记录ID")
        final_record_id = (
            None
            if record_id_pattern is None
            else extract_record_id(page.final_url, record_id_pattern)
        )
        if (
            record_id_pattern is not None
            and final_record_id != entry_record_id
        ):
            raise RecordBoundaryError("页面跳转后记录ID发生变化")
        documents: list[Document] = []
        seen_fingerprints: set[str] = set()

        def append_document(
            source: DocumentSource,
            source_url: str,
            content: str,
            record_id: str | None = None,
        ) -> None:
            fingerprint = hashlib.sha256(
                content.encode("utf-8", errors="replace")
            ).hexdigest()
            if fingerprint in seen_fingerprints:
                return
            seen_fingerprints.add(fingerprint)
            documents.append(
                Document(
                    document_id=_document_id(source, source_url, content),
                    source=source,
                    source_url=source_url,
                    order=len(documents),
                    content=content,
                    record_id=record_id,
                )
            )

        def append_with_decoded(
            source: DocumentSource,
            source_url: str,
            content: str,
            record_id: str | None = None,
        ) -> None:
            append_document(source, source_url, content, record_id)
            for index, decoded in enumerate(
                decode_embedded_text(content),
                start=1,
            ):
                append_document(
                    source,
                    f"{source_url}#decoded-{index}",
                    decoded,
                    record_id,
                )

        append_with_decoded(
            DocumentSource.PAGE,
            page.final_url,
            page.text,
            entry_record_id,
        )
        parser = _ReferenceParser()
        parser.feed(page.text)

        seen_urls = {page.final_url}
        inline_index = 0
        for reference in parser.references:
            if reference.source == DocumentSource.SCRIPT and not options.fetch_scripts:
                continue
            if reference.source == DocumentSource.IFRAME and not options.fetch_iframes:
                continue
            if reference.inline:
                inline_index += 1
                source_url = f"{page.final_url}#inline-script-{inline_index}"
                content = reference.value
            else:
                source_url = urljoin(page.final_url, reference.value)
                same_origin = _same_origin(page.final_url, source_url)
                allowed_hosts = {
                    host.casefold() for host in options.allowed_external_hosts
                }
                source_host = (urlparse(source_url).hostname or "").casefold()
                allowed_external = source_host in allowed_hosts
                if not options.allow_cross_origin and not (
                    same_origin or allowed_external
                ):
                    continue
                if (
                    reference.source == DocumentSource.SCRIPT
                    and options.script_path_markers
                    and not any(
                        marker.casefold() in source_url.casefold()
                        for marker in options.script_path_markers
                    )
                ):
                    continue
                if source_url in seen_urls:
                    continue
                seen_urls.add(source_url)
                response = self._client.fetch_text(
                    source_url,
                    required_origin=None if options.allow_cross_origin else source_url,
                )
                source_url = response.final_url
                content = response.text

            append_with_decoded(
                reference.source,
                source_url,
                content,
                (
                    None
                    if record_id_pattern is None
                    else extract_record_id(source_url, record_id_pattern)
                ),
            )

        for request in options.additional_requests:
            if request.source not in {
                DocumentSource.API,
                DocumentSource.SCRIPT,
                DocumentSource.IFRAME,
            }:
                raise ValueError(
                    f"附加文档来源不受支持：{request.source.value}"
                )
            request_url = urljoin(page.final_url, request.url)
            if (
                not options.allow_cross_origin
                and not _same_origin(page.final_url, request_url)
            ):
                continue
            response = self._client.fetch_text(
                request_url,
                required_origin=None
                if options.allow_cross_origin
                else page.final_url,
            )
            append_with_decoded(
                request.source,
                response.final_url,
                response.text,
                request.record_id
                or (
                    None
                    if record_id_pattern is None
                    else extract_record_id(response.final_url, record_id_pattern)
                ),
            )

        if options.render_browser:
            if self._browser_client is None:
                raise RuntimeError("未配置浏览器文档客户端")
            browser = self._browser_client.fetch_text(page.final_url)
            append_with_decoded(
                DocumentSource.BROWSER,
                browser.final_url,
                browser.text,
                (
                    None
                    if record_id_pattern is None
                    else extract_record_id(browser.final_url, record_id_pattern)
                ),
            )
        return tuple(documents)
