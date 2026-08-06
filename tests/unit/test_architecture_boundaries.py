from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ArchitectureBoundariesTest(unittest.TestCase):
    def test_domain_never_imports_infrastructure_layers(self) -> None:
        forbidden = {
            "banbo.fetch",
            "banbo.storage",
            "banbo.reporting",
            "banbo.application",
            "banbo.parsers",
        }
        violations: list[str] = []
        for path in (ROOT / "banbo" / "domain").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    if any(name == item or name.startswith(f"{item}.") for item in forbidden):
                        violations.append(f"{path.name}: {name}")

        self.assertEqual([], violations)

    def test_parsers_never_import_infrastructure_layers(self) -> None:
        forbidden = {
            "banbo.fetch",
            "banbo.storage",
            "banbo.reporting",
            "banbo.application",
        }
        violations: list[str] = []
        for path in (ROOT / "banbo" / "parsers").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    if any(name == item or name.startswith(f"{item}.") for item in forbidden):
                        violations.append(f"{path.name}: {name}")

        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
