import unittest
from types import SimpleNamespace

from audit.validate_shouzhudaitu_bottom_217 import (
    _article_documents,
    _collect_candidates,
)
from banbo.domain import Direction, Document, DocumentSource
from banbo.parsers.boundary import select_directional_window


def _document(order, suffix, content, *, parent="article.js"):
    return Document(
        document_id=f"doc-{parent}-{suffix}",
        source=DocumentSource.SCRIPT,
        source_url=f"https://data.test/{parent}#decoded-{suffix}",
        order=order,
        content=content,
    )


SITE = SimpleNamespace(name="守株待兔")
SPEC = SimpleNamespace(
    keywords=("精杀半波", "半波"),
    issue_pattern=r"(?P<issue>\d{1,4})期",
    value_pattern=r"(?P<value>[红绿蓝]\s*(?:波\s*)?[单双])",
)


class ShouzhudaituBottom217ValidationTest(unittest.TestCase):
    def _window(self, documents):
        _, article, _, _ = _article_documents(documents, SITE, SPEC)
        candidates = _collect_candidates(article, SITE, SPEC)
        return candidates, select_directional_window(
            candidates,
            issue_of=lambda candidate: candidate.issue,
            direction=Direction.BOTTOM,
        )[0]

    def test_bottom_window_excludes_earlier_same_issue(self):
        documents = (
            _document(0, 18, "217期: 守株待兔 精杀半波"),
            _document(1, 30, "217期 精杀半波 红单 开:猴46准"),
            _document(
                2,
                66,
                "215期 精杀半波 红双 216期 精杀半波 绿双 "
                "217期 精杀半波 绿单",
            ),
            _document(3, 67, "context_switch 上一篇 下一篇"),
        )

        candidates, window = self._window(documents)

        self.assertEqual([217, 215, 216, 217], [item.issue for item in candidates])
        self.assertEqual([215, 216, 217], [item.issue for item in window])
        self.assertEqual(["绿单"], [item.value for item in window if item.issue == 217])

    def test_navigation_end_excludes_next_article(self):
        documents = (
            _document(0, 18, "217期: 守株待兔 精杀半波"),
            _document(1, 66, "215期 精杀半波 红双 216期 精杀半波 绿双 217期 精杀半波 绿单"),
            _document(2, 67, "context_switch 上一篇 下一篇"),
            _document(3, 68, "217期 精杀半波 蓝双"),
        )

        candidates, window = self._window(documents)

        self.assertNotIn("蓝双", [item.value for item in candidates])
        self.assertEqual("绿单", [item.value for item in window if item.issue == 217][0])

    def test_anchor_cannot_be_borrowed_across_parent_scripts(self):
        documents = (
            _document(0, 18, "217期: 守株待兔 精杀半波", parent="title.js"),
            _document(1, 19, "context_switch 上一篇 下一篇", parent="title.js"),
            _document(2, 1, "217期 精杀半波 蓝双", parent="other.js"),
        )

        _, article, _, _ = _article_documents(documents, SITE, SPEC)

        self.assertEqual((), _collect_candidates(article, SITE, SPEC))

    def test_wrong_field_before_half_wave_keyword_is_ignored(self):
        documents = (
            _document(0, 18, "217期: 守株待兔 精杀半波"),
            _document(
                1,
                66,
                "215期 精杀半波 红双 216期 精杀半波 绿双 "
                "217期 杀一肖 红单 精杀半波 绿单",
            ),
            _document(2, 67, "context_switch 上一篇 下一篇"),
        )

        _, window = self._window(documents)

        self.assertEqual(["绿单"], [item.value for item in window if item.issue == 217])

    def test_two_values_after_keyword_remain_window_conflict(self):
        documents = (
            _document(0, 18, "217期: 守株待兔 精杀半波"),
            _document(
                1,
                66,
                "215期 精杀半波 红双 216期 精杀半波 绿双 "
                "217期 精杀半波 红单 精杀半波 绿单",
            ),
            _document(2, 67, "context_switch 上一篇 下一篇"),
        )

        _, window = self._window(documents)

        self.assertEqual(
            {"红单", "绿单"},
            {item.value for item in window if item.issue == 217},
        )


if __name__ == "__main__":
    unittest.main()
