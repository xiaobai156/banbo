import json
import unittest
from pathlib import Path

from banbo.parsers import build_default_registry, parse_parser_specs


ROOT = Path(__file__).resolve().parents[2]


class AllSiteSpecsContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sites = json.loads(
            (ROOT / "config" / "sites.json").read_text(encoding="utf-8")
        )["sites"]
        cls.specs = parse_parser_specs(
            json.loads(
                (ROOT / "config" / "parser_specs.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        cls.sites_by_id = {site["site_id"]: site for site in cls.sites}

    def test_every_formal_site_has_one_explicit_spec(self):
        site_ids = [site["site_id"] for site in self.sites]
        spec_ids = [spec.site_id for spec in self.specs]
        parser_ids = [spec.parser_id for spec in self.specs]
        self.assertEqual(len(site_ids), len(set(site_ids)))
        self.assertEqual(len(spec_ids), len(set(spec_ids)))
        self.assertEqual(len(parser_ids), len(set(parser_ids)))
        self.assertTrue(all(parser_ids))
        self.assertEqual(set(site_ids), set(spec_ids))

    def test_every_spec_declares_strict_business_boundaries(self):
        for spec in self.specs:
            with self.subTest(site_id=spec.site_id):
                self.assertTrue(spec.anchors)
                self.assertTrue(spec.keywords)
                self.assertTrue(spec.issue_pattern)
                self.assertTrue(spec.value_pattern)
                self.assertTrue(spec.parser_version)
                self.assertEqual(
                    self.sites_by_id[spec.site_id]["direction"],
                    spec.direction.value,
                )
                if spec.strategy == "regex_line":
                    self.assertTrue(spec.options.get("patterns"))

    def test_all_specs_bind_without_generic_fallback(self):
        registry = build_default_registry()
        for spec in self.specs:
            registry.bind(spec)
            self.assertIsNotNone(registry.parser_for(spec.site_id))


if __name__ == "__main__":
    unittest.main()
