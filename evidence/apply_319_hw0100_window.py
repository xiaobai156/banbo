# -*- coding: utf-8 -*-
"""把 hw-0100 丢六度路 的 title_neighbor 文档窗口 32 -> 64，并升 parser_version/parser_id。

只改 config/parser_specs.json 中 hw-0100 这一段，其余字节不动。
用法：py -3.10 evidence/apply_319_hw0100_window.py [--apply]
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SPECS = PROJECT / "config" / "parser_specs.json"


def main() -> int:
    apply = "--apply" in sys.argv
    text = SPECS.read_text(encoding="utf-8")

    marker = '"site_id": "hw-0100",'
    start = text.index(marker)
    end = text.index('"site_id": "hw-0101",', start)
    block = text[start:end]

    assert block.count('"after_documents": 32,') == 1, block.count('"after_documents": 32,')
    assert block.count('"parser_id": "hw-0100:title_neighbor:v1",') == 1
    assert block.count('"parser_version": "1",') == 1

    new_block = (
        block.replace('"after_documents": 32,', '"after_documents": 64,')
        .replace(
            '"parser_id": "hw-0100:title_neighbor:v1",',
            '"parser_id": "hw-0100:title_neighbor:v2",',
        )
        .replace('"parser_version": "1",', '"parser_version": "2",')
    )
    new_text = text[:start] + new_block + text[end:]

    payload = json.loads(new_text)
    spec = next(s for s in payload["specs"] if s["site_id"] == "hw-0100")
    assert spec["after_documents"] == 64
    assert spec["parser_version"] == "2"
    assert spec["parser_id"] == "hw-0100:title_neighbor:v2"
    assert spec["anchors"] == ["丢六度路"]
    assert spec["before_documents"] == 0

    print("hw-0100 before_documents=%d after_documents=%d version=%s id=%s"
          % (spec["before_documents"], spec["after_documents"],
             spec["parser_version"], spec["parser_id"]))

    if not apply:
        print("[dry-run] 未写入。")
        return 0

    fd, tmp = tempfile.mkstemp(dir=str(SPECS.parent), prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new_text)
        os.replace(tmp, SPECS)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    print("已写入：", SPECS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
