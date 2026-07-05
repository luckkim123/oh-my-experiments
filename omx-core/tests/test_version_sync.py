import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _plugin_version():
    return json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())["version"]


def _pyproject_version():
    text = (REPO / "omx-core" / "pyproject.toml").read_text()
    m = re.search(r'(?m)^version = "([^"]+)"$', text)
    assert m, "pyproject.toml has no version line"
    return m.group(1)


def test_versions_in_sync():
    """3-way drift guard (#6): plugin.json is the SSOT; pyproject must match.
    If this fails, run: python3 scripts/sync_version.py"""
    assert _pyproject_version() == _plugin_version()


def test_sync_script_is_idempotent(tmp_path):
    import subprocess, sys
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "sync_version.py")],
                       capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 0, r.stderr
    assert _pyproject_version() == _plugin_version()
