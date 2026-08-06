from __future__ import annotations

import base64
import re


_STRDECODE_RE = re.compile(
    r"\bstrdecode\s*\(\s*([\"'])([A-Za-z0-9+/=_-]+)\1\s*\)",
    re.IGNORECASE,
)
_UNICODE_ESCAPE_RE = re.compile(r"\\u[0-9a-fA-F]{4}")


def decode_embedded_text(text: str, *, max_depth: int = 3) -> tuple[str, ...]:
    decoded_documents: list[str] = []
    seen = {text}
    pending = [(text, 0)]
    while pending:
        current, depth = pending.pop(0)
        if depth >= max_depth:
            continue
        decoded_now: list[str] = []
        for match in _STRDECODE_RE.finditer(current):
            payload = match.group(2)
            try:
                raw = base64.b64decode(
                    payload + ("=" * (-len(payload) % 4))
                )
            except Exception:
                continue
            for encoding in ("utf-8", "gb18030", "big5"):
                try:
                    decoded_now.append(raw.decode(encoding))
                    break
                except UnicodeDecodeError:
                    continue

        if _UNICODE_ESCAPE_RE.search(current):
            unescaped = _UNICODE_ESCAPE_RE.sub(
                lambda match: chr(int(match.group(0)[2:], 16)),
                current,
            ).replace("\\/", "/")
            if unescaped != current:
                decoded_now.append(unescaped)

        for decoded in decoded_now:
            if not decoded or decoded in seen:
                continue
            seen.add(decoded)
            decoded_documents.append(decoded)
            pending.append((decoded, depth + 1))
    return tuple(decoded_documents)
