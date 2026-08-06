import unittest
from unittest.mock import ANY, patch

from banbo.application.multi_period import run_periods
from banbo.application.models import SiteRun
from banbo.application.single_period import (
    FetchedDocuments,
    SinglePeriodRunner,
    default_document_provider,
)
from banbo.domain import Direction, Document, DocumentSource, FailureCode, FailureResult
from banbo.parsers import ParserSpec, build_default_registry
from banbo.fetch import ResolvedArticle
from banbo.storage.site_repository import SiteRecord, SiteRepository


def document(content, order=0, record_id="1"):
    return Document(
        document_id=f"doc-{order}",
        source=DocumentSource.SCRIPT,
        source_url=f"https://example.test/{order}.js",
        order=order,
        content=content,
        record_id=record_id,
    )


def parser_spec(site_id="hw-0001"):
    return ParserSpec(
        site_id=site_id,
        strategy="history_block",
        direction=Direction.TOP,
        anchors=("专属站",),
        keywords=("绝杀半波",),
        parser_version="1",
        options={"window_size": 3},
    )


class SinglePeriodRunnerTest(unittest.TestCase):
    def site_repository(self):
        return SiteRepository(
            [
                SiteRecord(
                    site_id="hw-0001",
                    name="专属站",
                    url="https://example.test/topic/1.html",
                    direction=Direction.TOP,
                )
            ]
        )

    def registry(self):
        registry = build_default_registry()
        registry.bind(parser_spec())
        return registry

    def test_validated_result_is_created_only_after_parser_and_validator(self):
        calls = []

        def provider(site, spec, issue):
            calls.append((site.site_id, issue))
            return FetchedDocuments(
                (document("专属站\n211期 绝杀半波【蓝单】"),),
                request_url=site.url,
            )

        runner = SinglePeriodRunner(
            self.site_repository(),
            [parser_spec()],
            self.registry(),
            document_provider=provider,
        )

        run = runner.run_site("hw-0001", 211)

        self.assertEqual("蓝单", run.outcome.value)
        self.assertEqual([("hw-0001", 211)], calls)

    def test_article_list_source_resolves_article_before_document_discovery(self):
        site = SiteRecord(
            site_id="hw-list-0001",
            name="绿树成荫",
            url="https://list.example/list.aspx?id=79&page=1",
            direction=Direction.TOP,
            shared_url_group="list-79",
        )
        spec = ParserSpec(
            site_id=site.site_id,
            parser_id="hw-list-0001:history_block:v1",
            strategy="history_block",
            direction=Direction.TOP,
            anchors=("绿树成荫",),
            keywords=("绿树成荫",),
            parser_version="1",
            record_id_pattern=r"[?&]id=(?P<record_id>\d+)",
            options={
                "source": {
                    "kind": "article_list",
                    "title_anchor": "绿树成荫",
                    "title_suffix": "【绝杀半波】",
                    "next_text": "下一页",
                    "max_pages": 9,
                }
            },
        )
        article_document = document(
            "绿树成荫\n218期 绿树成荫【绿单】",
            record_id="972334",
        )
        resolved = ResolvedArticle(
            article_url="https://list.example/article.aspx?id=972334",
            title="218期:绿树成荫【绝杀半波】已免费公开",
            list_pages=(site.url,),
        )

        with (
            patch("banbo.application.single_period.HttpClient"),
            patch(
                "banbo.application.single_period.resolve_article_from_list",
                return_value=resolved,
            ) as resolver,
            patch("banbo.application.single_period.DocumentDiscoverer") as discoverer_type,
        ):
            discoverer_type.return_value.discover.return_value = (article_document,)

            fetched = default_document_provider(site, spec, 218)

        resolver.assert_called_once()
        self.assertEqual(site.url, resolver.call_args.args[1])
        self.assertEqual(218, resolver.call_args.args[2])
        discoverer_type.return_value.discover.assert_called_once_with(
            resolved.article_url,
            options=ANY,
            record_id_pattern=spec.record_id_pattern,
        )
        self.assertEqual("972334", fetched.expected_record_id)
        self.assertEqual(resolved.article_url, fetched.request_url)

    def test_missing_parser_spec_fails_without_fetch(self):
        called = False

        def provider(site, spec, issue):
            nonlocal called
            called = True
            raise AssertionError("不应访问未配置专属解析站点")

        runner = SinglePeriodRunner(
            self.site_repository(),
            [],
            build_default_registry(),
            document_provider=provider,
        )

        run = runner.run_site("hw-0001", 211)

        self.assertIsInstance(run.outcome, FailureResult)
        self.assertEqual(FailureCode.PARSER_SPEC_MISSING, run.outcome.code)
        self.assertFalse(called)

    def test_target_period_missing_does_not_borrow_adjacent_period(self):
        def provider(site, spec, issue):
            return FetchedDocuments(
                (document("专属站\n210期 绝杀半波【蓝单】"),),
            )

        runner = SinglePeriodRunner(
            self.site_repository(),
            [parser_spec()],
            self.registry(),
            document_provider=provider,
        )

        run = runner.run_site("hw-0001", 211)

        self.assertEqual(FailureCode.TARGET_PERIOD_MISSING, run.outcome.code)

    def test_unexpected_parser_error_is_not_reported_as_anchor_missing(self):
        def provider(site, spec, issue):
            raise ValueError("解析器配置损坏")

        runner = SinglePeriodRunner(
            self.site_repository(),
            [parser_spec()],
            self.registry(),
            document_provider=provider,
        )

        run = runner.run_site("hw-0001", 211)

        self.assertIsInstance(run.outcome, FailureResult)
        self.assertEqual(FailureCode.INTERNAL_ERROR, run.outcome.code)
        self.assertIn("ValueError", run.outcome.message)

    def test_run_many_rejects_duplicate_site_ids(self):
        runner = SinglePeriodRunner(
            self.site_repository(),
            [parser_spec()],
            self.registry(),
            document_provider=lambda site, spec, issue: FetchedDocuments(()),
        )

        with self.assertRaisesRegex(ValueError, "重复"):
            runner.run_many(211, site_ids=["hw-0001", "hw-0001"])

    def test_run_many_rejects_unknown_site_ids_before_workers_start(self):
        runner = SinglePeriodRunner(
            self.site_repository(),
            [parser_spec()],
            self.registry(),
            document_provider=lambda site, spec, issue: FetchedDocuments(()),
        )

        with self.assertRaisesRegex(ValueError, "未知站点"):
            runner.run_many(211, site_ids=["hw-missing"])

    def test_run_many_reports_progress_after_each_site(self):
        sites = SiteRepository(
            [
                SiteRecord(
                    site_id="hw-0001",
                    name="专属站一",
                    url="https://example.test/topic/1.html",
                    direction=Direction.TOP,
                ),
                SiteRecord(
                    site_id="hw-0002",
                    name="专属站二",
                    url="https://example.test/topic/2.html",
                    direction=Direction.TOP,
                ),
            ]
        )
        runner = SinglePeriodRunner(
            sites,
            [],
            build_default_registry(),
            document_provider=lambda site, spec, issue: FetchedDocuments(()),
        )
        updates = []

        def fake_run_site(site_id, target_issue):
            site = sites.get(site_id)
            return SiteRun(
                site,
                FailureResult(
                    site_id=site_id,
                    target_issue=target_issue,
                    code=FailureCode.TARGET_PERIOD_MISSING,
                    message="测试失败",
                ),
            )

        with patch.object(runner, "run_site", side_effect=fake_run_site):
            runs = runner.run_many(
                211,
                max_workers=1,
                progress_callback=updates.append,
            )

        self.assertEqual(2, len(runs))
        self.assertEqual([1, 2], [update.completed for update in updates])
        self.assertEqual([2, 2], [update.total for update in updates])
        self.assertEqual([0, 0], [update.succeeded for update in updates])
        self.assertEqual([1, 2], [update.failed for update in updates])
        self.assertEqual(["专属站一", "专属站二"], [
            update.site.name for update in updates
        ])

    def test_multi_period_passes_site_when_any_period_succeeds(self):
        def provider(site, spec, issue):
            value = "蓝单" if issue == 211 else ""
            return FetchedDocuments(
                (document(
                    "专属站\n"
                    + (f"{issue}期 绝杀半波【{value}】" if value else "210期 绝杀半波【红单】")
                ),)
            )

        runner = SinglePeriodRunner(
            self.site_repository(),
            [parser_spec()],
            self.registry(),
            document_provider=provider,
        )

        results = run_periods(runner, [211, 212])

        self.assertEqual(1, len(results))
        self.assertTrue(results[0].passed)
        self.assertIsNone(results[0].failure)


if __name__ == "__main__":
    unittest.main()
