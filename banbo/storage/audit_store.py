from __future__ import annotations

import os
from pathlib import Path

from .atomic_files import file_lock


class AuditLogRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, content: str) -> None:
        if not content:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        with file_lock(lock_path):
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
