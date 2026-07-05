#!/usr/bin/env python3
"""Sync the package version from .claude-plugin/plugin.json (the SSOT).

Fan-out target: omx-core/pyproject.toml (required). marketplace.json carries no
version field and README has no version marker — a marker is only ever UPDATED
where one already exists, never injected (spec 3.12). test_version_sync.py
asserts the sync so drift fails pytest.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    pyproject = ROOT / "omx-core" / "pyproject.toml"
    text = pyproject.read_text()
    new, n = re.subn(r'(?m)^version = "[^"]*"$', f'version = "{version}"', text, count=1)
    if n != 1:
        print("version line not found in omx-core/pyproject.toml", file=sys.stderr)
        return 2
    if new != text:
        pyproject.write_text(new)
    print(json.dumps({"version": version, "updated": ["omx-core/pyproject.toml"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
