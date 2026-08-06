from __future__ import annotations

import html
import re


def html_to_text(content: str) -> str:
    unescaped = html.unescape(content or "")
    without_tags = re.sub(r"<[^>]+>", "\n", unescaped)
    return without_tags.replace("\r\n", "\n").replace("\r", "\n")
