import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from banbo.domain import Direction, DocumentSource, FailureCode
from banbo.domain.models import FailureResult, ParseEvidence, ValidatedResult
from banbo.storage import (
    AuditLogRepository,
    CacheValidationError,
    ConcurrentModificationError,
    RecentCacheRepository,
    SiteRepository,
    atomic_write_text,
    commit_files,
    file_lock,
)
from banbo.storage.site_repository import SiteRecord


def result(site_id="hw-0001", issue=211, value="蓝单"):
    evidence = ParseEvidence(
        site_id=site_id,
        target_issue=issue,
        value=value,
        document_id="doc-1",
        document_source=DocumentSource.SCRIPT,
        document_order=1,
        snippet="211期 绝杀半波 蓝单",
        parser_name="test",
        parser_version="1",
        direction=Direction.TOP,
        anchor_passed=True,
        keyword_passed=True,
        same_record=True,
    )
    return ValidatedResult(
        site_id=site_id,
        site_name="甲站",
        target_issue=issue,
        value=value,
        direction=Direction.TOP,
        evidence=evidence,
        parser_version="1",
    )


class AtomicFilesTest(unittest.TestCase):
    def test_atomic_write_keeps_previous_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            atomic_write_text(path, "one")
            atomic_write_text(path, "two")

            self.assertEqual("two", path.read_text(encoding="utf-8"))
            self.assertEqual(
                "one",
                path.with_suffix(".json.bak").read_text(encoding="utf-8"),
            )
            self.assertFalse(path.with_name(".state.json.lock").exists())

    def test_lock_timeout_does_not_enter_locked_section(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "state.lock"
            with file_lock(lock):
                with self.assertRaises(TimeoutError):
                    with file_lock(lock, timeout=0):
                        pass

    def test_stale_lock_owned_by_dead_process_is_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "state.lock"
            lock.write_text("99999999", encoding="ascii")

            with file_lock(lock, timeout=0):
                self.assertTrue(lock.exists())

            self.assertFalse(lock.exists())

    def test_multi_file_commit_rolls_back_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "success.txt"
            second = Path(directory) / "cache.json"
            first.write_text("old success", encoding="utf-8")
            second.write_text("old cache", encoding="utf-8")

            calls = 0

            def replace_with_failure(source, target):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated replace failure")
                os.replace(source, target)

            with self.assertRaises(OSError):
                commit_files(
                    {first: "new success", second: "new cache"},
                    replace_func=replace_with_failure,
                )

            self.assertEqual("old success", first.read_text(encoding="utf-8"))
            self.assertEqual("old cache", second.read_text(encoding="utf-8"))

    def test_commit_rejects_stale_expected_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("old", encoding="utf-8")
            snapshot = path.read_bytes()

            path.write_text("new", encoding="utf-8")

            with self.assertRaises(ConcurrentModificationError):
                commit_files(
                    {path: "replacement"},
                    expected_digests={
                        path: __import__("hashlib")
                        .sha256(snapshot)
                        .hexdigest()
                    },
                )

            self.assertEqual("new", path.read_text(encoding="utf-8"))


class SiteRepositoryTest(unittest.TestCase):
    def test_duplicate_name_is_rejected(self):
        payload = [
            {
                "site_id": "hw-0001",
                "name": "重复",
                "url": "https://one.test/",
                "direction": "top",
            },
            {
                "site_id": "hw-0002",
                "name": "重复",
                "url": "https://two.test/",
                "direction": "bottom",
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sites.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                SiteRepository.from_json(path)

    def test_explicit_shared_entry_group_allows_same_list_url(self):
        records = [
            SiteRecord(
                site_id="hw-0001",
                name="甲站",
                url="https://list.example/list.aspx?id=79&page=1",
                direction=Direction.TOP,
                shared_url_group="list-79",
            ),
            SiteRecord(
                site_id="hw-0002",
                name="乙站",
                url="https://list.example/list.aspx?id=79&page=1",
                direction=Direction.TOP,
                shared_url_group="list-79",
            ),
        ]

        repository = SiteRepository(records)

        self.assertEqual(2, len(repository.all()))

    def test_same_url_without_explicit_shared_entry_group_is_rejected(self):
        records = [
            SiteRecord(
                site_id="hw-0001",
                name="甲站",
                url="https://list.example/list.aspx?id=79&page=1",
                direction=Direction.TOP,
            ),
            SiteRecord(
                site_id="hw-0002",
                name="乙站",
                url="https://list.example/list.aspx?id=79&page=1",
                direction=Direction.TOP,
            ),
        ]

        with self.assertRaisesRegex(ValueError, "URL重复"):
            SiteRepository(records)


class RecentCacheRepositoryTest(unittest.TestCase):
    def make_cache(self, path):
        path.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "window_size": 2,
                    "issues": [211, 210],
                    "sites": [
                        {
                            "name": "甲站",
                            "url": "https://example.test/",
                            "pick": "top",
                            "values": {"211": "红单", "210": "蓝双"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_updates_only_validated_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recent.json"
            self.make_cache(path)
            repository = RecentCacheRepository(path)
            payload = repository.update_existing_period(
                [result()],
                site_names_by_id={"hw-0001": "甲站"},
                target_issue=211,
                run_id="run-1",
            )

            self.assertEqual("蓝单", payload["sites"][0]["values"]["211"])
            self.assertEqual("run-1", payload["last_run_id"])

    def test_existing_period_requires_complete_formal_site_set(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recent.json"
            self.make_cache(path)

            with self.assertRaisesRegex(CacheValidationError, "站点数量"):
                RecentCacheRepository(path).prepare_existing_period(
                    [result()],
                    site_names_by_id={"hw-0001": "甲站"},
                    target_issue=211,
                    expected_site_count=2,
                    expected_site_names={"甲站", "乙站"},
                )

    def test_existing_period_merges_parser_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recent.json"
            self.make_cache(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["parser_versions"] = {
                "hw-old": "old-v1",
                "hw-0001": "old-v0",
            }
            path.write_text(json.dumps(payload), encoding="utf-8")

            updated = RecentCacheRepository(path).prepare_existing_period(
                [result()],
                site_names_by_id={"hw-0001": "甲站"},
                target_issue=211,
                expected_site_count=1,
                expected_site_names={"甲站"},
            )

            self.assertEqual(
                {"hw-old": "old-v1", "hw-0001": "1"},
                updated["parser_versions"],
            )

    def test_invalid_cache_window_type_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recent.json"
            self.make_cache(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["window_size"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(CacheValidationError, "窗口大小"):
                RecentCacheRepository(path).load()

    def test_failure_result_cannot_update_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recent.json"
            self.make_cache(path)
            failure = FailureResult(
                site_id="hw-0001",
                target_issue=211,
                code=FailureCode.TARGET_PERIOD_MISSING,
                message="missing",
            )
            with self.assertRaises(CacheValidationError):
                RecentCacheRepository(path).update_existing_period(
                    [failure],
                    site_names_by_id={"hw-0001": "甲站"},
                    target_issue=211,
                )

    def test_new_period_cannot_be_partially_added(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recent.json"
            self.make_cache(path)
            with self.assertRaises(CacheValidationError):
                RecentCacheRepository(path).update_existing_period(
                    [result(issue=212)],
                    site_names_by_id={"hw-0001": "甲站"},
                    target_issue=212,
                )

    def test_complete_new_period_advances_window(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recent.json"
            self.make_cache(path)
            payload = RecentCacheRepository(path).advance_complete_period(
                [result(issue=212)],
                site_names_by_id={"hw-0001": "甲站"},
                target_issue=212,
                expected_site_count=1,
                run_id="run-2",
            )

            self.assertEqual([212, 211], payload["issues"])
            self.assertEqual("蓝单", payload["sites"][0]["values"]["212"])

    def test_cache_validates_failure_metadata_and_value_exclusivity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recent.json"
            self.make_cache(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["sites"][0]["failures"] = {
                "211": {
                    "code": "target_period_missing",
                    "reason": "未找到目标期",
                }
            }
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(CacheValidationError, "同时成功和失败"):
                RecentCacheRepository(path).load()

            del payload["sites"][0]["values"]["211"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = RecentCacheRepository(path).load()
            self.assertEqual(
                "target_period_missing",
                loaded["sites"][0]["failures"]["211"]["code"],
            )

    def test_audit_append_is_serialized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            repository = AuditLogRepository(path)
            repository.append("one\n")
            repository.append("two\n")

            self.assertEqual("one\ntwo\n", path.read_text(encoding="utf-8"))

    def test_audit_append_flushes_to_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            with patch("banbo.storage.audit_store.os.fsync") as fsync:
                AuditLogRepository(path).append("one\n")

            self.assertGreaterEqual(fsync.call_count, 1)


if __name__ == "__main__":
    unittest.main()
