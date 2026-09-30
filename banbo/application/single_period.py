from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from dataclasses import dataclass
from functools import partial

from banbo.domain import (
    Document,
    DocumentSource,
    FailureCode,
    FailureResult,
    SiteSpec,
    validate_evidence,
)
from banbo.fetch import (
    ArticleListResolutionError,
    ArticleListSpec,
    DiscoveryOptions,
    DocumentDiscoverer,
    DocumentRequest,
    DynamicSourceError,
    DynamicSourceSpec,
    FetchError,
    HttpClient,
    RecordBoundaryError,
    fetch_dynamic_document,
    resolve_article_from_list,
)
from banbo.parsers import ParserRegistry, ParserSpec
from banbo.storage.site_repository import SiteRecord, SiteRepository

from .models import ProgressUpdate, SiteRun


@dataclass(frozen=True)
class FetchedDocuments:
    documents: tuple[Document, ...]
    expected_record_id: str | None = None
    request_url: str = ""


DocumentProvider = Callable[
    [SiteRecord, ParserSpec, int],
    FetchedDocuments,
]


def default_document_provider(
    site: SiteRecord,
    parser_spec: ParserSpec,
    target_issue: int,
    *,
    _client: HttpClient | None = None,
) -> FetchedDocuments:
    external_hosts = tuple(
            str(host).strip()
            for host in parser_spec.options.get(
                "allowed_external_hosts",
                tuple(
                    f"xia0{index}.cosds.ahsccn.com" for index in range(1, 7)
                ),
            )
            if str(host).strip()
        )
    options = DiscoveryOptions(
        allowed_external_hosts=external_hosts,
        script_path_markers=("/upload/script/", "/template/tags/", "/tags/"),
        link_external_scripts_to_entry=(
            parser_spec.link_external_scripts_to_entry
        ),
        additional_requests=tuple(
            DocumentRequest(
                source=DocumentSource(str(item["source"]).strip().lower()),
                url=str(item["url"]).strip(),
            )
            for item in parser_spec.options.get("additional_requests", ())
        ),
    )
    response_limit = parser_spec.options.get("max_response_bytes")
    verify_ssl = bool(parser_spec.options.get("verify_ssl", True))
    client_context = (
        nullcontext(_client)
        if (
            _client is not None
            and response_limit is None
            and verify_ssl
            and not parser_spec.options.get("allowed_external_hosts")
        )
        else HttpClient(
            timeout=20,
            retries=2,
            verify_ssl=verify_ssl,
            insecure_hosts=external_hosts,
            **(
                {}
                if response_limit is None
                else {"max_response_bytes": int(response_limit)}
            ),
        )
    )
    with client_context as client:
        source_options = parser_spec.options.get("source")
        if isinstance(source_options, Mapping):
            source_kind = str(source_options.get("kind", "")).strip()
            if source_kind == "article_list":
                resolved = resolve_article_from_list(
                    client,
                    site.url,
                    target_issue,
                    ArticleListSpec(
                        title_anchor=str(source_options["title_anchor"]),
                        title_suffix=str(source_options["title_suffix"]),
                        next_text=str(source_options["next_text"]),
                        max_pages=int(source_options["max_pages"]),
                    ),
                )
                record_pattern = (
                    parser_spec.record_id_pattern
                    or parser_spec.topic_id_pattern
                )
                documents = DocumentDiscoverer(client).discover(
                    resolved.article_url,
                    options=options,
                    record_id_pattern=record_pattern,
                )
                expected_record_id = (
                    documents[0].record_id if documents else None
                )
                return FetchedDocuments(
                    documents=documents,
                    expected_record_id=expected_record_id,
                    request_url=resolved.article_url,
                )
            dynamic_document = fetch_dynamic_document(
                client,
                site.url,
                target_issue,
                DynamicSourceSpec(
                    kind=str(source_options["kind"]),
                    user_id=str(source_options["user_id"]),
                    topic=str(source_options["topic"]),
                    sub_topic=(
                        None
                        if source_options.get("sub_topic") is None
                        else str(source_options["sub_topic"])
                    ),
                ),
            )
            return FetchedDocuments(
                documents=(dynamic_document,),
                expected_record_id=dynamic_document.record_id,
                request_url=site.url,
            )
        record_id_pattern = (
            parser_spec.record_id_pattern or parser_spec.topic_id_pattern
        )
        documents = DocumentDiscoverer(client).discover(
            site.url,
            options=options,
            record_id_pattern=record_id_pattern,
        )
        return FetchedDocuments(
            documents=documents,
            expected_record_id=(documents[0].record_id if documents else None),
            request_url=site.url,
        )


def build_site_spec(
    site: SiteRecord,
    parser_spec: ParserSpec,
    *,
    expected_record_id: str | None = None,
) -> SiteSpec:
    return SiteSpec(
        site_id=site.site_id,
        name=site.name,
        url=site.url,
        direction=site.direction,
        strategy=parser_spec.strategy,
        anchors=parser_spec.anchors,
        parser_version=parser_spec.parser_version,
        before_documents=parser_spec.before_documents,
        after_documents=parser_spec.after_documents,
        target_only=parser_spec.target_only,
        record_id_pattern=parser_spec.record_id_pattern,
        topic_id_pattern=parser_spec.topic_id_pattern,
        keywords=parser_spec.keywords,
        issue_pattern=parser_spec.issue_pattern or r"(?P<issue>\d{1,4})期",
        value_pattern=parser_spec.value_pattern
        or r"(?P<value>[红绿蓝](?:波)?[单双])",
        anchor_mode=str(parser_spec.options.get("anchor_mode", "all")),
        expected_record_id=expected_record_id,
    )


class SinglePeriodRunner:
    def __init__(
        self,
        sites: SiteRepository,
        parser_specs: Sequence[ParserSpec],
        registry: ParserRegistry,
        *,
        document_provider: DocumentProvider = default_document_provider,
    ) -> None:
        self._sites = sites
        self._specs = {spec.site_id: spec for spec in parser_specs}
        self._registry = registry
        self._document_provider = document_provider

    def run_site(self, site_id: str, target_issue: int) -> SiteRun:
        return self._run_site(site_id, target_issue, self._document_provider)

    def _run_site(
        self,
        site_id: str,
        target_issue: int,
        document_provider: DocumentProvider,
    ) -> SiteRun:
        site = self._sites.get(site_id)
        started = time.perf_counter()
        parser_spec = self._specs.get(site_id)
        if parser_spec is None:
            outcome = FailureResult(
                site_id=site_id,
                target_issue=target_issue,
                code=FailureCode.PARSER_SPEC_MISSING,
                message="没有站点专属解析规格，拒绝通用解析凑数",
            )
            return SiteRun(site, outcome, elapsed_ms=self._elapsed(started))
        try:
            fetched = document_provider(site, parser_spec, target_issue)
            site_spec = build_site_spec(
                site,
                parser_spec,
                expected_record_id=fetched.expected_record_id,
            )
            evidence = self._registry.parse(
                site_spec,
                fetched.documents,
                target_issue,
            )
            outcome = validate_evidence(site_spec, target_issue, evidence)
            return SiteRun(
                site,
                outcome,
                elapsed_ms=self._elapsed(started),
                document_count=len(fetched.documents),
                request_url=fetched.request_url or site.url,
            )
        except ArticleListResolutionError as exc:
            outcome = FailureResult(
                site_id=site_id,
                target_issue=target_issue,
                code=FailureCode.TARGET_PERIOD_MISSING,
                message=str(exc),
            )
        except DynamicSourceError as exc:
            outcome = FailureResult(
                site_id=site_id,
                target_issue=target_issue,
                code=FailureCode.TARGET_PERIOD_MISSING,
                message=str(exc),
            )
        except RecordBoundaryError as exc:
            outcome = FailureResult(
                site_id=site_id,
                target_issue=target_issue,
                code=FailureCode.RECORD_ID_MISMATCH,
                message=str(exc),
            )
        except FetchError as exc:
            outcome = FailureResult(
                site_id=site_id,
                target_issue=target_issue,
                code=self._fetch_failure_code(str(exc)),
                message=str(exc),
            )
        except Exception as exc:
            outcome = FailureResult(
                site_id=site_id,
                target_issue=target_issue,
                code=FailureCode.INTERNAL_ERROR,
                message=f"新版流程异常：{type(exc).__name__}: {exc}",
            )
        return SiteRun(
            site,
            outcome,
            elapsed_ms=self._elapsed(started),
            request_url=site.url,
        )

    def run_many(
        self,
        target_issue: int,
        *,
        site_ids: Sequence[str] | None = None,
        max_workers: int = 8,
        progress_callback: Callable[[ProgressUpdate], None] | None = None,
    ) -> list[SiteRun]:
        selected = list(
            site_ids
            if site_ids is not None
            else [
                site.site_id
                for site in self._sites.all()
                if not site.archived
            ]
        )
        if not selected:
            return []
        if len(selected) != len(set(selected)):
            raise ValueError("站点ID不能重复")
        known_site_ids = {site.site_id for site in self._sites.all()}
        unknown_site_ids = [
            site_id for site_id in selected if site_id not in known_site_ids
        ]
        if unknown_site_ids:
            raise ValueError(
                "未知站点：" + ",".join(str(site_id) for site_id in unknown_site_ids)
            )
        archived_site_ids = [
            site_id for site_id in selected if self._sites.get(site_id).archived
        ]
        if archived_site_ids:
            raise ValueError(
                "站点已封存，不再抓取：" + ",".join(archived_site_ids)
            )
        results: dict[str, SiteRun] = {}
        started = time.perf_counter()
        completed = 0
        succeeded = 0
        use_shared_client = self._document_provider is default_document_provider
        client_context = (
            HttpClient(timeout=20, retries=2)
            if use_shared_client
            else nullcontext()
        )
        with client_context as shared_client, ThreadPoolExecutor(
            max_workers=max(1, max_workers)
        ) as executor:
            provider = (
                partial(default_document_provider, _client=shared_client)
                if use_shared_client
                else self._document_provider
            )
            futures = {
                executor.submit(
                    self._run_site,
                    site_id,
                    target_issue,
                    provider,
                ): site_id
                for site_id in selected
            }
            for future in as_completed(futures):
                site_id = futures[future]
                run = future.result()
                results[site_id] = run
                completed += 1
                if run.succeeded:
                    succeeded += 1
                if progress_callback is not None:
                    progress_callback(
                        ProgressUpdate(
                            completed=completed,
                            total=len(selected),
                            succeeded=succeeded,
                            failed=completed - succeeded,
                            elapsed_seconds=time.perf_counter() - started,
                            site=run.site,
                            target_issue=target_issue,
                        )
                    )
        return [results[site_id] for site_id in selected]

    @staticmethod
    def _fetch_failure_code(message: str) -> FailureCode:
        lowered = message.casefold()
        if "ssl" in lowered or "证书" in lowered:
            return FailureCode.SSL_ERROR
        if "http请求失败" in message or "状态码" in message:
            return FailureCode.HTTP_ERROR
        return FailureCode.NETWORK_ERROR

    @staticmethod
    def _elapsed(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)
