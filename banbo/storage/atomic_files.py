from __future__ import annotations

import json
import hashlib
import os
import shutil
import time
import uuid
from collections.abc import Mapping
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Callable, Iterator


class LockTimeoutError(TimeoutError):
    pass


class ConcurrentModificationError(RuntimeError):
    pass


_UNSET = object()


def file_digest(path: str | Path) -> str | None:
    target = Path(path)
    if not target.exists():
        return None
    return hashlib.sha256(target.read_bytes()).hexdigest()


def read_text_snapshot(path: str | Path) -> tuple[str, str | None]:
    target = Path(path)
    if not target.exists():
        return "", None
    raw = target.read_bytes()
    return raw.decode("utf-8-sig"), hashlib.sha256(raw).hexdigest()


def _process_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _remove_stale_lock(path: Path) -> bool:
    try:
        owner = path.read_text(encoding="ascii").strip()
        pid = int(owner)
    except (FileNotFoundError, OSError, ValueError):
        return False
    if _process_alive(pid):
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return True
    return True


@contextmanager
def file_lock(
    lock_path: str | Path,
    *,
    timeout: float = 10.0,
    poll_interval: float = 0.05,
) -> Iterator[None]:
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(
                path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
            os.write(descriptor, str(os.getpid()).encode("ascii"))
            os.fsync(descriptor)
        except FileExistsError:
            if _remove_stale_lock(path):
                continue
            if time.monotonic() >= deadline:
                raise LockTimeoutError(f"文件锁超时：{path}")
            time.sleep(poll_interval)
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def atomic_write_text(
    path: str | Path,
    content: str,
    *,
    lock_timeout: float = 10.0,
    expected_digest: str | None | object = _UNSET,
) -> None:
    commit_files(
        {Path(path): content},
        lock_timeout=lock_timeout,
        expected_digests=(
            {Path(path): expected_digest}
            if expected_digest is not _UNSET
            else None
        ),
    )


def render_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def commit_files(
    operations: Mapping[str | Path, str | None],
    *,
    expected_digests: Mapping[str | Path, str | None] | None = None,
    lock_timeout: float = 10.0,
    replace_func: Callable[[str | Path, str | Path], None] = os.replace,
) -> None:
    normalized = {Path(path): content for path, content in operations.items()}
    if not normalized:
        return
    targets = sorted(normalized, key=lambda path: str(path).casefold())
    expected = {
        Path(path): digest for path, digest in (expected_digests or {}).items()
    }
    unknown_expected = set(expected) - set(targets)
    if unknown_expected:
        raise ValueError("并发校验路径必须同时出现在提交操作中")
    rollback_snapshots: dict[Path, Path | None] = {}
    temporary_files: dict[Path, Path] = {}
    with ExitStack() as stack:
        for target in targets:
            stack.enter_context(
                file_lock(
                    target.with_name(f".{target.name}.lock"),
                    timeout=lock_timeout,
                )
            )
        try:
            for target, expected_digest in expected.items():
                actual_digest = file_digest(target)
                if actual_digest != expected_digest:
                    raise ConcurrentModificationError(
                        f"文件在读取后已变化，拒绝覆盖：{target}"
                    )
            for target in targets:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    snapshot = target.with_name(
                        f".{target.name}.{uuid.uuid4().hex}.rollback"
                    )
                    shutil.copy2(target, snapshot)
                    rollback_snapshots[target] = snapshot
                else:
                    rollback_snapshots[target] = None
                content = normalized[target]
                if content is not None:
                    temporary = target.with_name(
                        f".{target.name}.{uuid.uuid4().hex}.tmp"
                    )
                    with temporary.open(
                        "w", encoding="utf-8", newline="\n"
                    ) as handle:
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
                    temporary_files[target] = temporary

            for target in targets:
                content = normalized[target]
                if content is None:
                    try:
                        target.unlink()
                    except FileNotFoundError:
                        pass
                else:
                    replace_func(temporary_files[target], target)
        except Exception:
            for target in reversed(targets):
                if target not in rollback_snapshots:
                    continue
                snapshot = rollback_snapshots.get(target)
                try:
                    if snapshot is not None and snapshot.exists():
                        replace_func(snapshot, target)
                    elif target.exists():
                        target.unlink()
                except OSError:
                    pass
            raise
        finally:
            for temporary in (*temporary_files.values(), *rollback_snapshots.values()):
                if temporary is None:
                    continue
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass


def atomic_write_json(
    path: str | Path,
    payload: object,
    *,
    lock_timeout: float = 10.0,
    expected_digest: str | None | object = _UNSET,
) -> None:
    atomic_write_text(
        path,
        render_json(payload),
        lock_timeout=lock_timeout,
        expected_digest=expected_digest,
    )
