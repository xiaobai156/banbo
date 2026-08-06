import unittest

from banbo.adaptive import (
    AdaptiveMatchRejected,
    AdaptiveOptions,
    ScraplingAdapter,
    StructureProfile,
)
from banbo.domain import Document, DocumentSource


def document(document_id="doc-1"):
    return Document(
        document_id=document_id,
        source=DocumentSource.PAGE,
        source_url="https://example.test/",
        order=0,
        content="211期绝杀半波蓝单",
    )


class AdaptiveBoundaryTest(unittest.TestCase):
    def test_disabled_adaptive_layer_returns_no_candidates(self):
        adapter = ScraplingAdapter(lambda docs, profile: docs)

        self.assertEqual((), adapter.locate((document(),), None))

    def test_untrusted_profile_fails_closed(self):
        adapter = ScraplingAdapter(lambda docs, profile: docs)

        with self.assertRaises(AdaptiveMatchRejected):
            adapter.locate(
                (document(),),
                StructureProfile(status="candidate"),
                options=AdaptiveOptions(enabled=True),
            )

    def test_locator_cannot_invent_document(self):
        adapter = ScraplingAdapter(lambda docs, profile: (document("other"),))

        with self.assertRaises(AdaptiveMatchRejected):
            adapter.locate(
                (document(),),
                StructureProfile(status="trusted"),
                options=AdaptiveOptions(enabled=True),
            )


if __name__ == "__main__":
    unittest.main()
