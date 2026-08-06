from __future__ import annotations

import sys
from typing import TextIO

from banbo.application.models import ProgressUpdate


def format_progress_line(update: ProgressUpdate) -> str:
    percent = int(update.completed * 100 / update.total) if update.total else 100
    return (
        f"[进度 {update.completed}/{update.total} {percent}% "
        f"成功 {update.succeeded} 失败 {update.failed} "
        f"用时 {update.elapsed_seconds:.1f}s] 当前：{update.site.name}"
    )


class ConsoleProgress:
    def __init__(self, *, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stdout
        self._last_length = 0

    def __call__(self, update: ProgressUpdate) -> None:
        line = format_progress_line(update)
        padding = " " * max(0, self._last_length - len(line))
        self._stream.write(f"\r{line}{padding}")
        self._stream.flush()
        self._last_length = len(line)

    def finish(self) -> None:
        if self._last_length:
            self._stream.write("\n")
            self._stream.flush()
            self._last_length = 0
