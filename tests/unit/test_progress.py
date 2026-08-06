import io
import unittest

from banbo.application.models import ProgressUpdate
from banbo.domain import Direction
from banbo.reporting.progress import ConsoleProgress
from banbo.storage.site_repository import SiteRecord


class ConsoleProgressTest(unittest.TestCase):
    def test_progress_line_matches_requested_format(self):
        site = SiteRecord(
            site_id="hw-test",
            name="梨花飞雪",
            url="https://example.test/",
            direction=Direction.TOP,
        )
        update = ProgressUpdate(
            completed=5,
            total=163,
            succeeded=5,
            failed=0,
            elapsed_seconds=2.7,
            site=site,
            target_issue=211,
        )
        output = io.StringIO()
        progress = ConsoleProgress(stream=output)

        progress(update)
        progress.finish()

        self.assertEqual(
            "\r[进度 5/163 3% 成功 5 失败 0 用时 2.7s] 当前：梨花飞雪\n",
            output.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
