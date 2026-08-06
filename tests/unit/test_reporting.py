import tempfile
import unittest
from pathlib import Path

from banbo.application.models import SiteRun
from banbo.domain import Direction, DocumentSource, FailureCode
from banbo.domain.models import FailureResult, ParseEvidence, ValidatedResult
from banbo.reporting import (
    append_audit_jsonl,
    render_audit_jsonl,
    render_failure_report,
    render_multi_failure_report,
    render_success_report,
    write_failure_report,
)
from banbo.application.multi_period import MultiPeriodSiteResult
from banbo.storage.site_repository import SiteRecord


def site(name, direction=Direction.TOP):
    return SiteRecord(
        site_id=f"hw-{name}",
        name=name,
        url=f"https://{name}.test/",
        direction=direction,
    )


def success(name, value):
    evidence = ParseEvidence(
        site_id=f"hw-{name}",
        target_issue=211,
        value=value,
        document_id="doc-1",
        document_source=DocumentSource.SCRIPT,
        document_order=1,
        snippet="211期 绝杀半波",
        parser_name="history_block",
        parser_version="2",
        direction=Direction.TOP,
        anchor_passed=True,
        keyword_passed=True,
        same_record=True,
        candidate_count=1,
    )
    return SiteRun(
        site(name),
        ValidatedResult(
            site_id=f"hw-{name}",
            site_name=name,
            target_issue=211,
            value=value,
            direction=Direction.TOP,
            evidence=evidence,
            parser_version="2",
        ),
    )


class ReportingTest(unittest.TestCase):
    def test_failure_report_uses_requested_single_line_contract(self):
        failed = SiteRun(
            site("送钱猛料", Direction.BOTTOM),
            FailureResult(
                site_id="hw-送钱猛料",
                target_issue=215,
                code=FailureCode.INTERNAL_ERROR,
                message=(
                    "新版流程异常：LookupError: "
                    "绝对bottom边界是214期，不是指定215期"
                ),
            ),
        )

        content = render_failure_report(215, [failed])

        self.assertEqual(
            "失败 送钱猛料 https://送钱猛料.test/ 方向: bottom 期数: 215 "
            "阶段: 抓取/解析 原因: 抓取/解析失败(LookupError: "
            "绝对bottom边界是214期，不是指定215期)\n",
            content,
        )

    def test_failure_sites_have_one_blank_line_between_records(self):
        first = SiteRun(
            site("甲"),
            FailureResult(
                site_id="hw-甲",
                target_issue=211,
                code=FailureCode.ANCHOR_MISSING,
                message="未找到专属锚点",
            ),
        )
        second = SiteRun(
            site("乙"),
            FailureResult(
                site_id="hw-乙",
                target_issue=211,
                code=FailureCode.TARGET_PERIOD_MISSING,
                message="未找到目标期",
            ),
        )

        content = render_failure_report(211, [first, second])

        self.assertEqual(1, content.count("\n\n"))
        self.assertIn(
            "失败 甲 https://甲.test/ 方向: top 期数: 211 "
            "阶段: 目标定位 原因: 未找到专属锚点",
            content,
        )
        self.assertNotIn("失败类别", content)

    def test_no_failure_removes_stale_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "211期-半波-失败.txt"
            path.write_text("stale", encoding="utf-8")

            self.assertFalse(write_failure_report(path, 211, []))
            self.assertFalse(path.exists())

    def test_success_report_includes_rank(self):
        content = render_success_report(
            211,
            [success("甲", "蓝单"), success("乙", "蓝单"), success("丙", "红单")],
        )

        self.assertIn("蓝单\t甲", content)
        self.assertIn("211期排行", content)
        self.assertIn("1\t蓝单\t2", content)

    def test_audit_keeps_parser_and_document_evidence(self):
        content = render_audit_jsonl([success("甲", "蓝单")], run_id="run-1")

        self.assertIn('"run_id": "run-1"', content)
        self.assertIn('"parser": "history_block"', content)
        self.assertIn('"document_id": "doc-1"', content)

    def test_audit_append_rejects_incomplete_existing_record(self):
        with self.assertRaisesRegex(ValueError, "末尾"):
            append_audit_jsonl('{"run_id":"old"}', "new\n")

    def test_audit_append_rejects_malformed_existing_json(self):
        with self.assertRaisesRegex(ValueError, "无效JSON"):
            append_audit_jsonl("not-json\n", "new\n")

    def test_multi_failure_report_lists_only_all_failed_sites(self):
        failed = SiteRun(
            site("甲"),
            FailureResult(
                site_id="hw-甲",
                target_issue=211,
                code=FailureCode.TARGET_PERIOD_MISSING,
                message="未找到目标期",
            ),
        )
        failed_next = SiteRun(
            site("甲"),
            FailureResult(
                site_id="hw-甲",
                target_issue=210,
                code=FailureCode.ANCHOR_MISSING,
                message="未找到锚点",
            ),
        )
        passed = SiteRun(site("乙"), success("乙", "蓝单").outcome)
        results = (
            MultiPeriodSiteResult("hw-甲", (failed, failed_next)),
            MultiPeriodSiteResult("hw-乙", (passed,)),
        )

        content = render_multi_failure_report(results)

        self.assertIn("甲", content)
        self.assertIn("期数: 211", content)
        self.assertIn("期数: 210", content)
        self.assertNotIn("乙", content)
        self.assertNotIn("全部指定期数失败", content)
        self.assertIn(
            "失败 甲 https://甲.test/ 方向: top 期数: 211 "
            "阶段: 指定期数校验 原因: 未找到目标期",
            content,
        )
        self.assertEqual(0, content.count("\n\n\n"))


if __name__ == "__main__":
    unittest.main()
