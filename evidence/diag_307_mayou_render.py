# -*- coding: utf-8 -*-
"""只读：Playwright 渲染 62139c.com，导出「码友书阳」区块及其 30x 期行，确认 307 是否发布。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).with_name("diag_307_mayou_render.txt")
URL = sys.argv[1] if len(sys.argv) > 1 else "https://62139c.com/"

with sync_playwright() as p:
    browser = p.chromium.launch(args=["--ignore-certificate-errors"])
    page = browser.new_page(ignore_https_errors=True, viewport={"width": 1400, "height": 1200})
    page.goto(URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(2500)
    text = page.evaluate("document.body.innerText")
    browser.close()

lines = [ln.strip() for ln in text.splitlines()]
idx = [i for i, ln in enumerate(lines) if "码友书阳" in ln]
print("rendered chars=%d lines=%d 书阳出现=%d" % (len(text), len(lines), len(idx)))
for i in idx:
    print("\n=== 书阳区块 @line %d ===" % i)
    print("\n".join(lines[i : i + 20]))
print("\n=== 全文 307 行 ===")
for ln in lines:
    if "307" in ln:
        print("  ", ln[:120])
OUT.write_text(text, encoding="utf-8")
print("\nsaved", OUT)
