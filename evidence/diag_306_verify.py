"""306 期失败站点逐站浏览器验证（只读）。

对失败TXT里的每个站点分别做 HTTP 与 Playwright 两路取证：
- ok/error：能否取到页面
- 是否有 306 期标记、页面最新期号、站点锚点
用于区分「异常」（能取到但解析不到）与「无数据」（站点没发 306）。
不写配置、缓存、正式输出。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from banbo.fetch.browser_client import BrowserClient  # noqa: E402
from banbo.fetch.http_client import HttpClient  # noqa: E402
from banbo.parsers.text import html_to_text  # noqa: E402

TARGET = "306"
NAMES = (
    "片言一字",
    "六合宝典",
    "完事五一",
    "此曲已终",
    "好彩网",
    "人定胜天",
    "被发徒跣",
    "残雪清寒",
)
OUT = ROOT / "evidence" / "diag_306_verify.json"
DUMP_DIR = ROOT / "evidence" / "diag_306_dumps"


def summarize(text: str, name: str) -> dict:
    issues = {}
    for match in re.finditer(r"(?<!\d)(\d{1,4})期", text):
        issues[match.group(1)] = issues.get(match.group(1), 0) + 1
    recent = sorted(
        (int(k), v) for k, v in issues.items() if 250 <= int(k) <= 400
    )
    return {
        "len": len(text),
        "has_target": f"{TARGET}期" in text,
        "count_target": text.count(f"{TARGET}期"),
        "anchor_name": text.count(name),
        "half_wave": text.count("杀半波"),
        "recent_issues": recent[-8:],
    }


def main() -> int:
    sites = json.loads(
        (ROOT / "config" / "sites.json").read_text(encoding="utf-8")
    )["sites"]
    url_by_name = {row["name"]: row["url"] for row in sites}
    DUMP_DIR.mkdir(exist_ok=True)
    http = HttpClient(timeout=20, retries=2)
    browser = BrowserClient(timeout=30, verify_ssl=False)
    report: dict = {}
    for name in NAMES:
        url = url_by_name[name]
        entry: dict = {"url": url}
        for lane, client in (("http", http), ("browser", browser)):
            try:
                resp = client.fetch_text(url)
                text = html_to_text(resp.text or "")
                entry[lane] = {"ok": True, **summarize(text, name)}
                dump = DUMP_DIR / f"{name}-{lane}.txt"
                dump.write_text(text, encoding="utf-8")
                entry[lane]["dump"] = str(dump)
            except Exception as exc:  # noqa: BLE001
                entry[lane] = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}"[:300],
                }
        report[name] = entry
        print(f"===== {name} {url}")
        for lane in ("http", "browser"):
            item = entry[lane]
            if item.get("ok"):
                print(
                    f"  {lane}: ok len={item['len']} 306={item['count_target']} "
                    f"锚点={item['anchor_name']} 近期期号={item['recent_issues']}"
                )
            else:
                print(f"  {lane}: FAIL {item['error'][:160]}")
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
