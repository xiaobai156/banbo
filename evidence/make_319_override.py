# -*- coding: utf-8 -*-
"""由 apply_318_manual_override.py 生成 319 期补录脚本（319=红双，曲湮浮安 hw-0001）。

只做定点替换，保证制表符/路径转义与原脚本逐字节一致：
- PERIOD 318 -> 319
- VALUE 绿双 -> 红双（跳过 CANON 常量行）
- 输出/失败文件名、排行标题 318 -> 319
"""
from __future__ import annotations

from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "apply_318_manual_override.py"
DST = BASE / "apply_319_manual_override.py"

src = SRC.read_text(encoding="utf-8")
out = []
for line in src.split("\n"):
    if "CANON" in line:
        out.append(line)
        continue
    line = line.replace("318", "319").replace("绿双", "红双")
    out.append(line)
text = "\n".join(out)

assert 'PERIOD = "319"' in text
assert 'VALUE = "红双"' in text
assert 'RANK_TITLE = "319期排行"' in text
assert '"红单", "红双", "绿单", "绿双", "蓝单", "蓝双"' in text
assert "319期-半波-失败.txt" in text

DST.write_text(text, encoding="utf-8", newline="\n")
print("written", DST)
