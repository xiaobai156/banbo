import unittest

from banbo.application.duplicate_check import detect_repeats


class DuplicateCheckTest(unittest.TestCase):
    def test_aligns_values_by_explicit_issue_number(self):
        findings = detect_repeats(
            {211: "蓝单", 210: "红双", 209: "绿单", 208: "红单"},
            {
                "同源站": {
                    211: "蓝单",
                    210: "红双",
                    209: "绿单",
                    208: "红双",
                }
            },
            candidate_name="候选",
        )

        self.assertEqual(1, len(findings))
        self.assertEqual((211, 210, 209), findings[0].issues)

    def test_missing_issue_breaks_continuous_run(self):
        findings = detect_repeats(
            {211: "蓝单", 209: "蓝单", 208: "蓝单"},
            {"同源站": {211: "蓝单", 209: "蓝单", 208: "蓝单"}},
            candidate_name="候选",
        )

        self.assertEqual((), findings)


if __name__ == "__main__":
    unittest.main()
