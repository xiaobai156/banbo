from __future__ import annotations

import time
import re
from dataclasses import dataclass
from threading import BoundedSemaphore, Lock, local
from typing import Protocol
from urllib.parse import urlparse


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "application/json;q=0.8,*/*;q=0.7"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
}


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class RawResponse:
    final_url: str
    status_code: int
    content: bytes
    encoding: str | None = None


@dataclass(frozen=True)
class FetchResponse:
    requested_url: str
    final_url: str
    status_code: int
    text: str


class Transport(Protocol):
    def request(
        self,
        url: str,
        *,
        timeout: float,
        verify_ssl: bool,
        headers: dict[str, str],
    ) -> RawResponse: ...

    def close(self) -> None: ...


class RequestsTransport:
    def __init__(self) -> None:
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("requests not available") from exc
        self._requests = requests
        self._local = local()
        self._sessions = []
        self._sessions_lock = Lock()

    def _session(self):
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._requests.Session()
            self._local.session = session
            with self._sessions_lock:
                self._sessions.append(session)
        return session

    def request(
        self,
        url: str,
        *,
        timeout: float,
        verify_ssl: bool,
        headers: dict[str, str],
    ) -> RawResponse:
        response = self._session().get(
            url,
            timeout=timeout,
            verify=verify_ssl,
            headers=headers,
            allow_redirects=True,
        )
        try:
            return RawResponse(
                final_url=str(response.url),
                status_code=int(response.status_code),
                content=bytes(response.content),
                encoding=response.encoding or response.apparent_encoding,
            )
        finally:
            response.close()

    def close(self) -> None:
        with self._sessions_lock:
            sessions, self._sessions = self._sessions, []
        for session in sessions:
            session.close()


def _origin(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    return parsed.scheme.lower(), parsed.netloc.lower()


class HttpClient:
    def __init__(
        self,
        *,
        transport: Transport | None = None,
        timeout: float = 20,
        verify_ssl: bool = True,
        retries: int = 2,
        retry_delay: float = 0.5,
        max_response_bytes: int = 8 * 1024 * 1024,
        headers: dict[str, str] | None = None,
        cache=None,
        per_host_limit: int = 2,
    ) -> None:
        self._transport = transport or RequestsTransport()
        self._timeout = timeout
        self._verify_ssl = verify_ssl
        self._retries = max(0, retries)
        self._retry_delay = max(0.0, retry_delay)
        self._max_response_bytes = max_response_bytes
        self._headers = dict(DEFAULT_HEADERS if headers is None else headers)
        from .request_cache import RequestCache

        self._cache = cache or RequestCache()
        self._per_host_limit = max(1, per_host_limit)
        self._host_limiters: dict[str, BoundedSemaphore] = {}
        self._host_limiters_lock = Lock()

    def fetch_text(
        self,
        url: str,
        *,
        required_origin: str | None = None,
    ) -> FetchResponse:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise FetchError(f"仅允许HTTP/HTTPS网址：{url}")
        if required_origin is not None and _origin(url) != _origin(required_origin):
            raise FetchError(f"派生请求必须同源：{url}")

        cache_key = (url, required_origin or "")
        return self._cache.get_or_create(
            cache_key,
            lambda: self._fetch_uncached(url, required_origin),
        )

    def _fetch_uncached(
        self,
        url: str,
        required_origin: str | None,
    ) -> FetchResponse:
        host = urlparse(url).netloc.lower()
        with self._host_limiters_lock:
            limiter = self._host_limiters.setdefault(
                host, BoundedSemaphore(self._per_host_limit)
            )
        last_error: Exception | None = None
        with limiter:
            for attempt in range(self._retries + 1):
                try:
                    raw = self._transport.request(
                        url,
                        timeout=self._timeout,
                        verify_ssl=self._verify_ssl,
                        headers=self._headers,
                    )
                    self._validate_response(url, raw, required_origin)
                    return FetchResponse(
                        requested_url=url,
                        final_url=raw.final_url,
                        status_code=raw.status_code,
                        text=self._decode(raw.content, raw.encoding),
                    )
                except Exception as exc:
                    last_error = exc
                    if attempt < self._retries and self._retry_delay:
                        time.sleep(self._retry_delay * (attempt + 1))

        if isinstance(last_error, FetchError):
            raise last_error
        raise FetchError(f"网络请求失败：{type(last_error).__name__}: {last_error}")

    def _validate_response(
        self,
        requested_url: str,
        response: RawResponse,
        required_origin: str | None,
    ) -> None:
        if not 200 <= response.status_code < 400:
            raise FetchError(
                f"HTTP请求失败：{response.status_code} {response.final_url}"
            )
        if len(response.content) > self._max_response_bytes:
            raise FetchError(f"响应内容超过大小限制：{requested_url}")
        requested_scheme = urlparse(requested_url).scheme.lower()
        final_scheme = urlparse(response.final_url).scheme.lower()
        if _origin(response.final_url) != _origin(requested_url):
            raise FetchError(f"响应跳转到其它源：{response.final_url}")
        if requested_scheme == "https" and final_scheme == "http":
            raise FetchError(f"禁止HTTPS降级跳转：{response.final_url}")
        if required_origin is not None and _origin(response.final_url) != _origin(
            required_origin
        ):
            raise FetchError(f"响应跳转到其它源：{response.final_url}")

    @staticmethod
    def _decode(content: bytes, encoding: str | None) -> str:
        # Some target sites declare ISO-8859-1 even though their page bytes are
        # UTF-8.  Prefer a strict UTF-8 decode, then honor the reported legacy
        # encoding when the bytes are not valid UTF-8.
        declared = re.search(
            rb"charset\s*=\s*[\"']?([A-Za-z0-9._-]+)",
            content[:8192],
            re.IGNORECASE,
        )
        declared_encoding = (
            declared.group(1).decode("ascii", errors="ignore")
            if declared
            else None
        )
        candidates = [declared_encoding, "utf-8", encoding, "gb18030", "big5"]
        for candidate in candidates:
            if not candidate:
                continue
            try:
                return content.decode(candidate)
            except (LookupError, UnicodeDecodeError):
                continue
        return content.decode("utf-8", errors="replace")

    def clear_cache(self) -> None:
        self._cache.clear()

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
