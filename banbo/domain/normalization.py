from __future__ import annotations

import html
import re
import unicodedata


ALLOWED_HALF_WAVE_VALUES = frozenset(
    {
        "红单",
        "红双",
        "绿单",
        "绿双",
        "蓝单",
        "蓝双",
    }
)

_WRAPPER_TRANSLATION = str.maketrans(
    {
        "【": " ",
        "】": " ",
        "[": " ",
        "]": " ",
        "（": " ",
        "）": " ",
        "(": " ",
        ")": " ",
        "《": " ",
        "》": " ",
        "〈": " ",
        "〉": " ",
        "<": " ",
        ">": " ",
        "『": " ",
        "』": " ",
        "「": " ",
        "」": " ",
    }
)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", html.unescape(value or ""))
    normalized = normalized.translate(_WRAPPER_TRANSLATION)
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_half_wave(value: str) -> str | None:
    normalized = normalize_text(value).replace(" ", "").replace("波", "")
    if normalized in ALLOWED_HALF_WAVE_VALUES:
        return normalized
    return None
