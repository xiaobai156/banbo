# -*- coding: utf-8 -*-
"""给 hw-0001 曲湮浮安 的关键词加上「绝杀一波」，并升 parser_version/parser_id。

原因：该站每期标题写「稳杀半波」，但当期正文只发 `N期: 绝杀一波 【X】开0000`，
半波历史表停在 310 期；「绝杀一波」不在关键词里，只能每期人工补录。
只改 config/parser_specs.json 中 hw-0001 这一段，其余字节不动。

用法：py -3.10 evidence/apply_321_hw0001_keyword.py [--apply]
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SPECS = PROJECT / "config" / "parser_specs.json"

OLD_KEYWORDS = '''      "keywords": [
        "绝杀半波",
        "杀半波",
        "稳杀半波",
        "精杀半波",
        "必杀半波"
      ],'''
NEW_KEYWORDS = '''      "keywords": [
        "绝杀半波",
        "杀半波",
        "稳杀半波",
        "精杀半波",
        "必杀半波",
        "绝杀一波"
      ],'''


def main() -> int:
    apply = "--apply" in sys.argv
    text = SPECS.read_text(encoding="utf-8")

    start = text.index('"site_id": "hw-0001",')
    end = text.index('"site_id": "hw-0002",', start)
    block = text[start:end]

    assert block.count(OLD_KEYWORDS) == 1, "hw-0001 关键词块不符合预期"
    assert block.count('"parser_id": "hw-0001:anchor_segment:v1",') == 1
    assert block.count('"parser_version": "1",') == 1
    assert "绝杀一波" not in block, "hw-0001 已含 绝杀一波"

    new_block = (
        block.replace(OLD_KEYWORDS, NEW_KEYWORDS)
        .replace(
            '"parser_id": "hw-0001:anchor_segment:v1",',
            '"parser_id": "hw-0001:anchor_segment:v2",',
        )
        .replace('"parser_version": "1",', '"parser_version": "2",')
    )
    new_text = text[:start] + new_block + text[end:]

    payload = json.loads(new_text)
    spec = next(s for s in payload["specs"] if s["site_id"] == "hw-0001")
    assert spec["keywords"] == [
        "绝杀半波", "杀半波", "稳杀半波", "精杀半波", "必杀半波", "绝杀一波",
    ], spec["keywords"]
    assert spec["parser_version"] == "2"
    assert spec["parser_id"] == "hw-0001:anchor_segment:v2"
    assert spec["anchors"] == ["曲湮浮安"]
    assert spec["options"]["max_issues"] == 13
    assert spec["options"]["window_size"] == 3

    print("hw-0001 keywords=%s version=%s id=%s"
          % (spec["keywords"], spec["parser_version"], spec["parser_id"]))

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
