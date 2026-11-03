# -*- coding: utf-8 -*-
"""最小补丁：把 hw-0109（赤兔）的 max_response_bytes 从 9MB 抬到 32MB。

只改 hw-0109 区块内的一行；改前断言该值在全文唯一。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "config" / "parser_specs.json"
OLD = '"max_response_bytes": 9437184'
NEW = '"max_response_bytes": 33554432'

raw = PATH.read_text(encoding="utf-8")
assert raw.count(OLD) == 1, "旧值出现次数异常：%d" % raw.count(OLD)

# 确认这唯一一处位于 hw-0109 区块内
idx = raw.index(OLD)
block_start = raw.rfind('"site_id": "hw-0109"', 0, idx)
next_site = raw.find('"site_id": "hw-0', idx)
assert block_start != -1 and (next_site == -1 or block_start < idx < next_site), "目标不在 hw-0109 区块"

patched = raw.replace(OLD, NEW)
data = json.loads(patched)  # 语法校验
spec = [s for s in data["specs"] if s["site_id"] == "hw-0109"][0]
assert spec["options"]["max_response_bytes"] == 33554432
assert spec["parser_id"] == "hw-0109:combined_sibling:v2"
PATH.write_text(patched, encoding="utf-8")
print("patched hw-0109 max_response_bytes -> 33554432")
print("parser_id 保持", spec["parser_id"])
_ = re
