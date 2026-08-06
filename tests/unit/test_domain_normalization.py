from __future__ import annotations

import unittest

from banbo.domain.normalization import (
    ALLOWED_HALF_WAVE_VALUES,
    normalize_half_wave,
    normalize_text,
)


class DomainNormalizationTest(unittest.TestCase):
    def test_normalizes_wrapped_wave_value(self) -> None:
        self.assertEqual("绿单", normalize_half_wave("【绿波单】"))
        self.assertEqual("蓝双", normalize_half_wave(" 蓝 波 双 "))

    def test_rejects_non_standard_wave_value(self) -> None:
        self.assertIsNone(normalize_half_wave("绿波"))
        self.assertIsNone(normalize_half_wave("红单尾"))

    def test_allowed_values_are_exactly_the_six_business_values(self) -> None:
        self.assertEqual(
            frozenset({"红单", "红双", "绿单", "绿双", "蓝单", "蓝双"}),
            ALLOWED_HALF_WAVE_VALUES,
        )

    def test_normalize_text_preserves_issue_boundaries(self) -> None:
        self.assertEqual(
            "210期 绝杀半波 绿单",
            normalize_text(" 210期\r\n绝杀半波\u3000【绿单】 "),
        )


if __name__ == "__main__":
    unittest.main()
