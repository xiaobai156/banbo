import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from banbo.cli import (
    RuntimeConfigurationError,
    _period_from_args,
    _prepare_cache_update,
    _validate_runtime_configuration,
    main,
)
from banbo.application.models import SiteRun
from banbo.domain import (
    Direction,
    DocumentSource,
    FailureCode,
    FailureResult,
    ParseEvidence,
    ValidatedResult,
)
from banbo.parsers import ParserSpec
from banbo.storage.atomic_files import commit_files as real_commit_files
from banbo.storage.site_repository import SiteRecord, SiteRepository


def site(site_id="hw-0001", direction=Direction.TOP):
    return SiteRecord(
        site_id=site_id,
        name=f"测试站-{site_id}",
        url=f"https://example.test/topic/{site_id}.html",
        direction=direction,
    )


def spec(site_id="hw-0001", direction=Direction.TOP):
    return ParserSpec(
        site_id=site_id,
        strategy="history_block",
        parser_version="1",
        parser_id=f"{site_id}:history_block:v1",
        direction=direction,
        anchors=("测试站",),
        keywords=("绝杀半波",),
    )


def validated_result(record, issue=215):
    evidence = ParseEvidence(
        site_id=record.site_id,
        target_issue=issue,
        value="蓝单",
        document_id="doc-1",
        document_source=DocumentSource.SCRIPT,
        document_order=0,
        snippet=f"{issue}期 绝杀半波 蓝单",
        parser_name="test",
        parser_version="1",
        direction=record.direction,
        anchor_passed=True,
        keyword_passed=True,
        same_record=True,
    )
    return ValidatedResult(
        site_id=record.site_id,
        site_name=record.name,
        target_issue=issue,
        value="蓝单",
        direction=record.direction,
        evidence=evidence,
        parser_version="1",
    )


class RuntimeConfigurationTest(unittest.TestCase):
    def test_site_and_parser_sets_must_match_exactly(self):
        sites = SiteRepository([site("hw-0001"), site("hw-0002")])

        with self.assertRaisesRegex(RuntimeConfigurationError, "缺少解析规格"):
            _validate_runtime_configuration(sites, [spec("hw-0001")])

    def test_site_and_parser_directions_must_match(self):
        sites = SiteRepository([site(direction=Direction.TOP)])

        with self.assertRaisesRegex(RuntimeConfigurationError, "方向"):
            _validate_runtime_configuration(sites, [spec(direction=Direction.BOTTOM)])


class PeriodArgumentTest(unittest.TestCase):
    def test_period_argument_requires_positive_integer(self):
        self.assertEqual(211, _period_from_args(211))
        with self.assertRaisesRegex(ValueError, "正整数"):
            _period_from_args(0)

    def test_period_is_read_when_not_provided(self):
        with patch("builtins.input", return_value="212"):
            self.assertEqual(212, _period_from_args(None))
        with patch("builtins.input", return_value="0"):
            with self.assertRaisesRegex(ValueError, "正整数"):
                _period_from_args(None)


class SinglePeriodCacheIsolationTest(unittest.TestCase):
    def _run(self, record):
        return SiteRun(record, validated_result(record))

    def _main_args(self, root):
        return [
            "--period",
            "215",
            "--success-dir",
            str(root / "success"),
            "--failure-dir",
            str(root / "failure"),
            "--cache",
            str(root / "recent_10_cache.json"),
        ]

    def _failure_run(self, record, issue=215):
        return SiteRun(
            record,
            FailureResult(
                site_id=record.site_id,
                target_issue=issue,
                code=FailureCode.TARGET_PERIOD_MISSING,
                message="未找到目标期",
            ),
        )

    def _write_cache(self, path, record):
        path.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "window_size": 2,
                    "issues": [211, 210],
                    "sites": [
                        {
                            "name": record.name,
                            "url": record.url,
                            "pick": "top",
                            "values": {"211": "红单", "210": "蓝双"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def _write_cache_many(self, path, records):
        path.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "window_size": 2,
                    "issues": [211, 210],
                    "sites": [
                        {
                            "name": record.name,
                            "url": record.url,
                            "pick": record.direction.value,
                            "values": {
                                "211": "红单",
                                "210": "蓝双",
                            },
                        }
                        for record in records
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_cache_update_branches_are_separate_from_live_runs(self):
        record = site()
        repository = SiteRepository([record])

        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "recent.json"
            self._write_cache(cache_path, record)

            message, payload, digest = _prepare_cache_update(
                cache_path,
                repository,
                211,
                [self._failure_run(record)],
                run_id="run-failure",
            )
            self.assertEqual("未补充缓存：本轮没有成功结果", message)
            self.assertIsNone(payload)
            self.assertIsNone(digest)

            message, payload, digest = _prepare_cache_update(
                cache_path,
                repository,
                211,
                [self._run_with_issue(record, 211)],
                run_id="run-existing",
            )
            self.assertEqual("补充已有缓存期", message)
            self.assertEqual("蓝单", payload["sites"][0]["values"]["211"])
            self.assertIsNotNone(digest)

            message, payload, digest = _prepare_cache_update(
                cache_path,
                repository,
                212,
                [self._failure_run(record, issue=212)],
                run_id="run-partial",
            )
            self.assertEqual(
                "未推进缓存：成功率0.00%未超过85%（0/1）", message
            )
            self.assertIsNone(payload)
            self.assertIsNone(digest)

            message, payload, digest = _prepare_cache_update(
                cache_path,
                repository,
                212,
                [self._run_with_issue(record, 212)],
                run_id="run-new",
            )
            self.assertEqual(
                "推进缓存新期：成功率100.00%（1/1）", message
            )
            self.assertEqual([212, 211], payload["issues"])
            self.assertEqual("蓝单", payload["sites"][0]["values"]["212"])
            self.assertIsNotNone(digest)

    def test_new_period_advances_above_85_percent_and_marks_failures(self):
        records = [site(f"hw-{index:04d}") for index in range(1, 164)]
        repository = SiteRepository(records)
        runs = [
            self._run_with_issue(record, 217)
            if index < 139
            else self._failure_run(record, issue=217)
            for index, record in enumerate(records)
        ]

        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "recent.json"
            self._write_cache_many(cache_path, records)

            message, payload, digest = _prepare_cache_update(
                cache_path,
                repository,
                217,
                runs,
                run_id="run-85-percent",
            )

            self.assertEqual(
                "推进缓存新期：成功率85.28%（139/163）", message
            )
            self.assertEqual(217, payload["issues"][0])
            self.assertEqual(
                "蓝单", payload["sites"][0]["values"]["217"]
            )
            self.assertNotIn("217", payload["sites"][0].get("failures", {}))
            failed = payload["sites"][-1]
            self.assertNotIn("217", failed["values"])
            self.assertEqual(
                {
                    "code": "target_period_missing",
                    "reason": "未找到目标期",
                },
                failed["failures"]["217"],
            )
            self.assertIsNotNone(digest)

    def test_new_period_rejects_85_percent_or_incomplete_site_run(self):
        records = [site(f"hw-{index:04d}") for index in range(1, 21)]
        repository = SiteRepository(records)
        exact_85_runs = [
            self._run_with_issue(record, 217)
            if index < 17
            else self._failure_run(record, issue=217)
            for index, record in enumerate(records)
        ]

        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "recent.json"
            self._write_cache_many(cache_path, records)

            message, payload, _ = _prepare_cache_update(
                cache_path,
                repository,
                217,
                exact_85_runs,
                run_id="run-exact-85",
            )
            self.assertEqual(
                "未推进缓存：成功率85.00%未超过85%（17/20）", message
            )
            self.assertIsNone(payload)

            message, payload, _ = _prepare_cache_update(
                cache_path,
                repository,
                217,
                exact_85_runs[:17],
                run_id="run-incomplete",
            )
            self.assertEqual("未推进缓存：必须执行完整全站任务", message)
            self.assertIsNone(payload)

    def _run_with_issue(self, record, issue):
        return SiteRun(record, validated_result(record, issue))

    def test_shadow_mode_does_not_write_outputs_or_cache(self):
        record = site()
        repository = SiteRepository([record])
        runner = Mock()
        runner.run_many.return_value = [self._run(record)]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch("banbo.cli.BASE_DIR", root),
                patch(
                    "banbo.cli._load_runtime",
                    return_value=(repository, (), object()),
                ),
                patch("banbo.cli.SinglePeriodRunner", return_value=runner),
            ):
                code = main(self._main_args(root) + ["--shadow"])

            self.assertEqual(0, code)
            self.assertFalse((root / "success").exists())
            self.assertFalse((root / "failure").exists())
            self.assertFalse((root / "recent_10_cache.json").exists())

    def test_cache_preparation_runs_after_output_commit(self):
        record = site()
        repository = SiteRepository([record])
        runner = Mock()
        events = []

        def run_many(*args, **kwargs):
            events.append("run")
            return [self._run(record)]

        runner.run_many.side_effect = run_many

        def prepare(*args, **kwargs):
            events.append("prepare")
            return "推进缓存新期", {"schema": 1}, None

        def commit(operations, **kwargs):
            events.append(
                ("commit", tuple(Path(path).name for path in operations))
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch("banbo.cli.BASE_DIR", root),
                patch(
                    "banbo.cli._load_runtime",
                    return_value=(repository, (), object()),
                ),
                patch("banbo.cli.SinglePeriodRunner", return_value=runner),
                patch("banbo.cli._prepare_cache_update", side_effect=prepare),
                patch("banbo.cli.commit_files", side_effect=commit),
            ):
                code = main(self._main_args(root))

        self.assertEqual(0, code)
        self.assertEqual("run", events[0])
        self.assertEqual("prepare", events[2])
        self.assertEqual("commit", events[1][0])
        self.assertNotIn("recent_10_cache.json", events[1][1])
        self.assertEqual(("commit", ("recent_10_cache.json",)), events[3])

    def test_cache_preparation_failure_keeps_realtime_outputs_and_result(self):
        record = site()
        repository = SiteRepository([record])
        runner = Mock()
        runner.run_many.return_value = [self._run(record)]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stdout = io.StringIO()
            with (
                patch("banbo.cli.BASE_DIR", root),
                patch(
                    "banbo.cli._load_runtime",
                    return_value=(repository, (), object()),
                ),
                patch("banbo.cli.SinglePeriodRunner", return_value=runner),
                patch(
                    "banbo.cli._prepare_cache_update",
                    side_effect=RuntimeError("缓存结构无效"),
                ),
                redirect_stdout(stdout),
            ):
                code = main(self._main_args(root))

            success_path = root / "success" / "215期-半波.txt"
            failure_path = root / "failure" / "215期-半波-失败.txt"
            cache_path = root / "recent_10_cache.json"
            self.assertTrue(success_path.exists())
            self.assertIn("蓝单\t测试站-hw-0001", success_path.read_text())
            self.assertFalse(failure_path.exists())
            self.assertFalse(cache_path.exists())
            self.assertIn("缓存更新未完成", stdout.getvalue())
            self.assertEqual(0, code)

    def test_cache_commit_failure_keeps_realtime_outputs_and_result(self):
        record = site()
        repository = SiteRepository([record])
        runner = Mock()
        runner.run_many.return_value = [self._run(record)]
        calls = 0

        def commit_then_fail(operations, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("磁盘写入失败")
            return real_commit_files(operations, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stdout = io.StringIO()
            with (
                patch("banbo.cli.BASE_DIR", root),
                patch(
                    "banbo.cli._load_runtime",
                    return_value=(repository, (), object()),
                ),
                patch("banbo.cli.SinglePeriodRunner", return_value=runner),
                patch(
                    "banbo.cli._prepare_cache_update",
                    return_value=("推进缓存新期", {"schema": 1}, None),
                ),
                patch("banbo.cli.commit_files", side_effect=commit_then_fail),
                redirect_stdout(stdout),
            ):
                code = main(self._main_args(root))

            success_path = root / "success" / "215期-半波.txt"
            cache_path = root / "recent_10_cache.json"
            self.assertTrue(success_path.exists())
            self.assertIn("蓝单\t测试站-hw-0001", success_path.read_text())
            self.assertFalse(cache_path.exists())
            self.assertIn("缓存更新未完成", stdout.getvalue())
            self.assertEqual(0, code)
            self.assertEqual(2, calls)


if __name__ == "__main__":
    unittest.main()
