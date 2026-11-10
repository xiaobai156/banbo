# -*- coding: utf-8 -*-
"""只读核对某期落盘结果：成功TXT、失败TXT、缓存、审计。
用法：py -3.10 evidence/verify_landing.py <period> [site_id/名称...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT_DIR = Path(r"C:\Users\Administrator\Desktop\每天工具\爬虫合集\七类数据统一归纳")
FAIL_DIR = Path(r"C:\Users\Administrator\Desktop\每天工具\爬虫合集\七类数据统一归纳失败")
PROJECT = Path(__file__).resolve().parents[1]

PERIOD = int(sys.argv[1])
WATCH = sys.argv[2:]

ok_path = OUT_DIR / f"{PERIOD}期-半波.txt"
fail_path = FAIL_DIR / f"{PERIOD}期-半波-失败.txt"

print("== 成功TXT ==", ok_path)
text = ok_path.read_text(encoding="utf-8")
lines = text.split("\n")
data: list[tuple[str, str]] = []
rank_start = 0
for i, line in enumerate(lines):
    if "排行" in line:
        rank_start = i
        break
    if "\t" in line:
        value, name = line.split("\t", 1)
        data.append((value, name.strip()))
names = [n for _, n in data]
print("数据行", len(data), "唯一站点", len(set(names)))
print("重复站点", sorted({n for n in names if names.count(n) > 1}))
if WATCH:
    for target in WATCH:
        print("  ", target, [(v, n) for v, n in data if n == target])
print("排行区:")
for line in lines[rank_start:]:
    if line.strip():
        print("   ", line)
total = 0
for line in lines[rank_start + 2:]:
    parts = line.split("\t")
    if len(parts) >= 3 and parts[2].strip().isdigit():
        total += int(parts[2])
print("统计合计", total)

print("\n== 失败TXT ==", fail_path, "exists=", fail_path.exists())
if fail_path.exists():
    for line in fail_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            print("   ", line)

print("\n== 缓存 ==")
cache = json.loads((PROJECT / "recent_10_cache.json").read_text(encoding="utf-8"))
print("updated", cache.get("updated_at"), "issues", cache.get("issues"))
sites = cache.get("sites") or {}
items = sites.items() if isinstance(sites, dict) else [(s.get("site_id"), s) for s in sites]
have = 0
for key, rec in items:
    values = rec.get("values") or {}
    if str(PERIOD) in values:
        have += 1
    name = rec.get("name")
    if WATCH and name in WATCH:
        print("  ", name, key, "value=", values.get(str(PERIOD)),
              "parser_versions=", rec.get("parser_versions"),
              "failure=", (rec.get("failures") or {}).get(str(PERIOD)))
print(f"{PERIOD} 有值站", have)

print("\n== 审计 ==")
audit = PROJECT / "audit" / f"{PERIOD}.jsonl"
if audit.exists():
    rows = [json.loads(x) for x in audit.read_text(encoding="utf-8").splitlines() if x.strip()]
    print("audit 行数", len(rows))
    for rec in rows[-3:]:
        print("  ", rec.get("site_id"), rec.get("site_name"), rec.get("value"),
              rec.get("failure_code"), rec.get("failure_stage"))
