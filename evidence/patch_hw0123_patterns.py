"""一次性外科补丁：给 hw-0123 三条 regex_line 模式加 (?<!\\d) 防伪期号，并升 parser_id/parser_version。

只改 config/parser_specs.json 中 hw-0123 区块的第 4406-4429 行范围内的 5 处；不生成 .bak。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "config" / "parser_specs.json"

lines = PATH.read_text(encoding="utf-8").splitlines(keepends=True)
start = next(i for i, line in enumerate(lines) if '"site_id": "hw-0123"' in line)
end = next(
    i for i in range(start + 1, len(lines)) if lines[i].strip() in {"},", "}"} and "]" not in lines[i]
)

changed: list[str] = []
for index in range(start, min(end, len(lines))):
    line = lines[index]
    if '"parser_id": "hw-0123:regex_line:v1"' in line:
        lines[index] = line.replace("hw-0123:regex_line:v1", "hw-0123:regex_line:v2")
        changed.append("parser_id")
    elif '"{issue}期' in line:
        lines[index] = line.replace('"{issue}期', '"(?<!\\\\d){issue}期', 1)
        changed.append(f"pattern@{index + 1}")
    elif line.strip() == '"parser_version": "1",':
        lines[index] = line.replace('"parser_version": "1"', '"parser_version": "2"')
        changed.append("parser_version")

assert len([c for c in changed if c.startswith("pattern@")]) == 3, changed
assert "parser_id" in changed and "parser_version" in changed, changed
PATH.write_text("".join(lines), encoding="utf-8")
print("changed:", changed)
