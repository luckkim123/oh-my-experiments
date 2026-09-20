#!/usr/bin/env python3
"""Sync the package version from .claude-plugin/plugin.json (the SSOT).

Fan-out targets: omx-core/pyproject.toml and omx_core/__init__.py's
`__version__` (both required). marketplace.json carries no version field and
README has no version marker — a marker is only ever UPDATED where one
already exists, never injected (spec 3.12). test_version_sync.py asserts all
three stay in sync so drift fails pytest.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sub_one(path: Path, pattern: str, replacement: str) -> bool:
    text = path.read_text()
    new, n = re.subn(pattern, replacement, text, count=1)
    if n != 1:
        print(f"version line not found in {path}", file=sys.stderr)
        sys.exit(2)
    if new != text:
        path.write_text(new)
        return True
    return False


def main() -> int:
    version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    updated = []
    if _sub_one(ROOT / "omx-core" / "pyproject.toml",
                r'(?m)^version = "[^"]*"$', f'version = "{version}"'):
        updated.append("omx-core/pyproject.toml")
    if _sub_one(ROOT / "omx-core" / "omx_core" / "__init__.py",
                r'(?m)^__version__ = "[^"]*"$', f'__version__ = "{version}"'):
        updated.append("omx-core/omx_core/__init__.py")
    print(json.dumps({"version": version, "updated": updated}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
