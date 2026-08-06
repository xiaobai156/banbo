from __future__ import annotations

import time
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Mapping, Sequence

from banbo.domain import (
    Document,
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
) -> FetchedDocuments:
    options = DiscoveryOptions(
        allowed_external_hosts=tuple(
            f"xia0{index}.cosds.ahsccn.com" for index in range(1, 7)
        ),
        script_path_markers=("/upload/script/", "/template/tags/", "/tags/"),
    )
    with HttpClient(timeout=20, retries=2) as client:
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
        documents = DocumentDiscoverer(client).discover(
            site.url,
            options=options,
        )
        return FetchedDocuments(
            documents=documents,
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
            fetched = self._document_provider(site, parser_spec, target_issue)
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
            else [site.site_id for site in self._sites.all()]
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
        results: dict[str, SiteRun] = {}
        started = time.perf_counter()
        completed = 0
        succeeded = 0
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
            futures = {
                executor.submit(self.run_site, site_id, target_issue): site_id
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
