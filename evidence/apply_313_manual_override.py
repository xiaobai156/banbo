# -*- coding: utf-8 -*-
"""按用户指定值把 曲湮浮安（hw-0001）313 期=红双 补进正式输出与近 10 期缓存。

背景：站点 313 期标题为「313期:曲湮浮安【稳杀半波】独家提供」，但正文只发布
`313期:绝杀一波【红双】开0000准`，稳杀半波表止于 310 期，CLI 按规则判
target_period_missing；用户看图后明确指定该站 313 期取 红双，故做一次受控人工补录
（不改配置、不改解析器），写入采用临时文件 + 原子替换。

用法：
    py -3.10 evidence/apply_313_manual_override.py --dry-run
    py -3.10 evidence/apply_313_manual_override.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

PROJECT = Path(r"C:\Users\Administrator\Desktop\每天工具\爬虫合集\杀半波_修复版2")
OUT_TXT = PROJECT.parent / "七类数据统一归纳" / "313期-半波.txt"
FAIL_TXT = PROJECT.parent / "七类数据统一归纳失败" / "313期-半波-失败.txt"
CACHE = PROJECT / "recent_10_cache.json"

SITE_NAME = "曲湮浮安"
SITE_URL = "https://fcgjgjid.w2io3-ne9v9-kfcwxa.work:17466/topic/554809.html"
PERIOD = "313"
VALUE = "红双"
CANON = ["红单", "红双", "绿单", "绿双", "蓝单", "蓝双"]
RANK_TITLE = "313期排行"
RANK_HEADER = "排名\t内容\t数量"


def atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def build_ranking(rows: list[tuple[str, str]]) -> list[str]:
    counts = {v: 0 for v in CANON}
    for value, _name in rows:
        counts[value] = counts.get(value, 0) + 1
    ordered = sorted(
        ((v, c) for v, c in counts.items() if c),
        key=lambda item: (-item[1], CANON.index(item[0])),
    )
    return ["%d\t%s\t%d" % (idx, value, count) for idx, (value, count) in enumerate(ordered, start=1)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    text = OUT_TXT.read_text(encoding="utf-8")
    ends_with_nl = text.endswith("\n")
    lines = text.split("\n")
    title_at = lines.index(RANK_TITLE)
    assert lines[title_at + 1] == RANK_HEADER, "排行表头不符: %r" % lines[title_at + 1]
    body = lines[:title_at]
    old_rank = [ln for ln in lines[title_at + 1 :] if ln.strip()]
    while body and not body[-1].strip():
        body.pop()

    rows = []
    for line in body:
        value, name = line.split("\t")
        assert value in CANON, "非法半波值: %r" % value
        rows.append((value, name))
    assert len(rows) == 196, "数据行应为 196，实际 %d" % len(rows)
    assert len({n for _v, n in rows}) == len(rows), "输出存在重复站点"
    names = [n for _v, n in rows]
    assert SITE_NAME not in names, "输出已含 %s" % SITE_NAME

    cfg = json.loads((PROJECT / "config" / "sites.json").read_text(encoding="utf-8"))
    active = [s["name"] for s in cfg["sites"] if not s.get("archived")]
    assert SITE_NAME in active, "配置缺少 %s" % SITE_NAME
    cfg_idx = active.index(SITE_NAME)

    prev_name = next((active[i] for i in range(cfg_idx - 1, -1, -1) if active[i] in names), None)
    next_name = next(
        (active[i] for i in range(cfg_idx + 1, len(active)) if active[i] in names), None
    )
    insert_at = 0 if prev_name is None else names.index(prev_name) + 1
    if next_name:
        assert names[insert_at] == next_name, "配置相邻顺序不符：%s 之后应为 %s，实际 %s" % (
            prev_name,
            next_name,
            names[insert_at],
        )
    rows.insert(insert_at, (VALUE, SITE_NAME))

    ranked = build_ranking(rows)
    new_text = (
        "\n".join("%s\t%s" % (v, n) for v, n in rows)
        + "\n\n\n"
        + RANK_TITLE
        + "\n"
        + RANK_HEADER
        + "\n"
        + "\n".join(ranked)
    )
    if ends_with_nl:
        new_text += "\n"

    print("插入位置：第 %d 条（在 %s 之后，%s 之前）" % (insert_at + 1, prev_name, next_name))
    print("数据行 %d -> %d；唯一站点 %d" % (len(names), len(rows), len({n for _v, n in rows})))
    print("排行 旧:", " | ".join(old_rank))
    print("排行 新:", " | ".join(ranked))
    print("合计", sum(int(line.split("\t")[2]) for line in ranked))

    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    entry = next(s for s in cache["sites"] if s["name"] == SITE_NAME)
    assert entry["url"] == SITE_URL, "缓存 URL 不符: %r" % entry["url"]
    assert PERIOD in (entry.get("failures") or {}), "缓存无 313 失败记录"
    old_value = (entry.get("values") or {}).get(PERIOD)

    fail_lines = []
    if FAIL_TXT.exists():
        fail_lines = [ln for ln in FAIL_TXT.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(fail_lines) == 1 and SITE_NAME in fail_lines[0], "失败清单应为该站 1 行: %r" % fail_lines

    if args.dry_run or not args.apply:
        print("[dry-run] 未写入。")
        return 0

    atomic_write(OUT_TXT, new_text)

    entry.setdefault("values", {})[PERIOD] = VALUE
    entry["values"] = {k: entry["values"][k] for k in sorted(entry["values"], key=int)}
    (entry.get("failures") or {}).pop(PERIOD, None)
    atomic_write(CACHE, json.dumps(cache, ensure_ascii=False, indent=2) + "\n")

    if fail_lines:
        FAIL_TXT.unlink()
        print("失败清单已清空并删除文件")

    print("已写入：", OUT_TXT)
    print("缓存 313：", old_value, "->", entry["values"][PERIOD], "| failures:", entry.get("failures") or {})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
