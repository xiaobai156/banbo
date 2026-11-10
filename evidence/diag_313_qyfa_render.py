# -*- coding: utf-8 -*-
"""只读：用 Playwright 渲染指定 URL，打印正文文本并标出关键行（期号/半波）。
用法：py -3.10 evidence/diag_313_qyfa_render.py <url> [period]
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

URL = sys.argv[1]
PERIOD = sys.argv[2] if len(sys.argv) > 2 else ""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(ignore_https_errors=True)
        page.goto(URL, timeout=45000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        text = page.inner_text("body")
        browser.close()
    print("URL", URL, "len", len(text))
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for idx, line in enumerate(lines):
        if ("半波" in line) or (PERIOD and (PERIOD + "期") in line) or ("一期" in line):
            print("  %4d | %s" % (idx, line[:160]))
    print("\n---- 含关键字的行数 ----", len(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
