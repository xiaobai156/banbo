import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from banbo.application.models import SiteRun
from banbo.application.multi_period import MultiPeriodSiteResult
from banbo.domain import Direction, FailureCode, FailureResult
from banbo.multi_cli import main
from banbo.storage.site_repository import SiteRecord, SiteRepository


class MultiCliTransactionTest(unittest.TestCase):
    def test_all_multi_outputs_are_submitted_once(self):
        site = SiteRecord(
            site_id="hw-test",
            name="测试站",
            url="https://example.test/",
            direction=Direction.TOP,
        )
        repository = SiteRepository([site])
        runs = tuple(
            SiteRun(
                site,
                FailureResult(
                    site_id=site.site_id,
                    target_issue=issue,
                    code=FailureCode.TARGET_PERIOD_MISSING,
                    message="未找到目标期",
                ),
            )
            for issue in (211, 210)
        )
        result = MultiPeriodSiteResult(site.site_id, runs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch(
                    "banbo.multi_cli._load_runtime",
                    return_value=(repository, (), None),
                ),
                patch(
                    "banbo.multi_cli.run_periods",
                    return_value=(result,),
                ),
                patch("banbo.multi_cli.commit_files") as commit,
            ):
                code = main(
                    [
                        "--periods",
                        "211",
                        "210",
                        "--success-dir",
                        str(root / "success"),
                        "--failure-dir",
                        str(root / "failure"),
                    ]
                )

        self.assertEqual(1, code)
        commit.assert_called_once()
        operations = commit.call_args.args[0]
        self.assertEqual(7, len(operations))
        self.assertTrue(
            any(path.name.endswith("-全部失败.txt") for path in operations)
        )

    def test_multi_commit_failure_does_not_report_success(self):
        site = SiteRecord(
            site_id="hw-test",
            name="测试站",
            url="https://example.test/",
            direction=Direction.TOP,
        )
        repository = SiteRepository([site])
        run = SiteRun(
            site,
            FailureResult(
                site_id=site.site_id,
                target_issue=211,
                code=FailureCode.TARGET_PERIOD_MISSING,
                message="未找到目标期",
            ),
        )
        result = MultiPeriodSiteResult(site.site_id, (run,))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch(
                    "banbo.multi_cli._load_runtime",
                    return_value=(repository, (), None),
                ),
                patch(
                    "banbo.multi_cli.run_periods",
                    return_value=(result,),
                ),
                patch(
                    "banbo.multi_cli.commit_files",
                    side_effect=OSError("disk full"),
                ),
            ):
                code = main(
                    [
                        "--periods",
                        "211",
                        "--success-dir",
                        str(root / "success"),
                        "--failure-dir",
                        str(root / "failure"),
                    ]
                )

        self.assertEqual(2, code)


if __name__ == "__main__":
    unittest.main()
