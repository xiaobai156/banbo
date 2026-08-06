import unittest

from banbo.domain.models import (
    Direction,
    Document,
    DocumentSource,
    ParseEvidence,
    SiteSpec,
    ValidatedResult,
)
from banbo.parsers.protocol import ParserSpec
from banbo.parsers.registry import (
    ParserRegistry,
    ParserRegistryError,
    build_default_registry,
)


class StubParser:
    name = "stub"
    version = "1"

    def __init__(self, spec):
        self.spec = spec

    def parse(self, site, documents, target_issue):
        return (
            ParseEvidence(
                site_id=site.site_id,
                target_issue=target_issue,
                value="绿单",
                document_id="doc",
                document_source=DocumentSource.PAGE,
                document_order=0,
                snippet="209期绿单",
                parser_name=self.name,
                parser_version=self.version,
                direction=site.direction,
                anchor_passed=True,
                keyword_passed=True,
                same_record=True,
                boundary_issues=(target_issue,),
            ),
        )


def make_site():
    return SiteSpec(
        site_id="site-a",
        name="站点A",
        url="https://example.test/a",
        direction=Direction.TOP,
        strategy="stub",
        anchors=("站点A",),
        parser_version="1",
    )


class ParserRegistryTest(unittest.TestCase):
    def test_resolves_bound_site_parser(self):
        registry = ParserRegistry()
        registry.register_strategy("stub", StubParser)
        registry.bind(
            ParserSpec(
                site_id="site-a",
                strategy="stub",
                parser_version="1",
            )
        )

        evidence = registry.parse(
            make_site(),
            (
                Document(
                    document_id="doc",
                    source=DocumentSource.PAGE,
                    source_url="https://example.test/a",
                    order=0,
                    content="209期绿单",
                ),
            ),
            209,
        )

        self.assertEqual("绿单", evidence[0].value)
        self.assertEqual("site-a:stub:v1", evidence[0].parser_id)
        self.assertEqual("https://example.test/a", evidence[0].source_url)

    def test_registry_rejects_duplicate_parser_id(self):
        registry = ParserRegistry()
        registry.register_strategy("stub", StubParser)
        first = ParserSpec(
            site_id="site-a",
            parser_id="shared",
            strategy="stub",
            parser_version="1",
        )
        second = ParserSpec(
            site_id="site-b",
            parser_id="shared",
            strategy="stub",
            parser_version="1",
        )
        registry.bind(first)
        with self.assertRaisesRegex(ParserRegistryError, "parser_id重复"):
            registry.bind(second)

    def test_unknown_strategy_is_rejected_at_bind_time(self):
        registry = ParserRegistry()

        with self.assertRaisesRegex(ParserRegistryError, "未注册"):
            registry.bind(
                ParserSpec(
                    site_id="site-a",
                    strategy="missing",
                    parser_version="1",
                )
            )

    def test_duplicate_site_binding_is_rejected(self):
        registry = ParserRegistry()
        registry.register_strategy("stub", StubParser)
        spec = ParserSpec(
            site_id="site-a",
            strategy="stub",
            parser_version="1",
        )
        registry.bind(spec)

        with self.assertRaisesRegex(ParserRegistryError, "重复"):
            registry.bind(spec)

    def test_parser_cannot_return_validated_result(self):
        class InvalidParser(StubParser):
            def parse(self, site, documents, target_issue):
                return (
                    ValidatedResult(
                        site_id=site.site_id,
                        site_name=site.name,
                        target_issue=target_issue,
                        value="绿单",
                        direction=site.direction,
                        evidence=StubParser(self.spec).parse(
                            site, documents, target_issue
                        )[0],
                        parser_version="1",
                    ),
                )

        registry = ParserRegistry()
        registry.register_strategy("invalid", InvalidParser)
        registry.bind(
            ParserSpec(
                site_id="site-a",
                strategy="invalid",
                parser_version="1",
            )
        )
        site = SiteSpec(
            site_id="site-a",
            name="站点A",
            url="https://example.test/a",
            direction=Direction.TOP,
            strategy="invalid",
            anchors=("站点A",),
            parser_version="1",
        )

        with self.assertRaisesRegex(ParserRegistryError, "ParseEvidence"):
            registry.parse(site, (), 209)

    def test_duplicate_document_ids_are_rejected(self):
        registry = ParserRegistry()
        registry.register_strategy("stub", StubParser)
        registry.bind(
            ParserSpec(site_id="site-a", strategy="stub", parser_version="1")
        )
        document = Document(
            document_id="doc",
            source=DocumentSource.PAGE,
            source_url="https://example.test/a",
            order=0,
            content="209期绿单",
        )

        with self.assertRaisesRegex(ParserRegistryError, "文档ID重复"):
            registry.parse(make_site(), (document, document), 209)

    def test_default_registry_contains_all_standard_strategies(self):
        registry = build_default_registry()

        for strategy in (
            "anchor_segment",
            "article_sibling_segment",
            "history_block",
            "nearest_document",
            "scoped_line",
            "regex_line",
            "title_neighbor",
            "split_document",
            "table",
            "dynamic_api",
        ):
            options = (
                {"patterns": [r"{issue}期(?P<value>红单)"]}
                if strategy == "regex_line"
                else {}
            )
            registry.bind(
                ParserSpec(
                    site_id=f"site-{strategy}",
                    strategy=strategy,
                    parser_version="1",
                    options=options,
                )
            )


if __name__ == "__main__":
    unittest.main()
