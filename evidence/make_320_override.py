# -*- coding: utf-8 -*-
"""由 apply_319_manual_override.py 定点生成 320 期补录脚本（不写正式文件）。"""
from __future__ import annotations

import io
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SRC = PROJECT / "evidence" / "apply_319_manual_override.py"
DST = PROJECT / "evidence" / "apply_320_manual_override.py"
OLD_PERIOD, NEW_PERIOD = "319", "320"
OLD_VALUE, NEW_VALUE = "红双", "绿双"

text = io.open(SRC, encoding="utf-8").read()
out = []
for line in text.split("\n"):
    if "CANON" in line:
        out.append(line)
        continue
    out.append(line.replace(OLD_PERIOD, NEW_PERIOD).replace(OLD_VALUE, NEW_VALUE))
result = "\n".join(out)

assert 'PERIOD = "320"' in result, "期号替换失败"
assert 'VALUE = "绿双"' in result, "取值替换失败"
assert 'RANK_TITLE = "320期排行"' in result, "排行标题替换失败"
assert 'CANON = ["红单", "红双", "绿单", "绿双", "蓝单", "蓝双"]' in result, "CANON 被误改"
assert "320期-半波-失败.txt" in result, "失败文件路径未更新"
io.open(DST, "w", encoding="utf-8", newline="\n").write(result)
print("written", DST)
print("period/value:", NEW_PERIOD, NEW_VALUE)
