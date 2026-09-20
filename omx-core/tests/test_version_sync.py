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


def _init_version():
    text = (REPO / "omx-core" / "omx_core" / "__init__.py").read_text()
    m = re.search(r'(?m)^__version__ = "([^"]+)"$', text)
    assert m, "omx_core/__init__.py has no __version__ line"
    return m.group(1)


def test_versions_in_sync():
    """3-way drift guard (#6): plugin.json is the SSOT; pyproject.toml and
    omx_core/__init__.py's __version__ must both match it. Deliberately NOT
    importlib.metadata.version("omx-core") — an editable install's dist-info
    is written once at install time and never tracks a pyproject.toml edit,
    so that value is an environment artifact (measured 0.5.0 against a
    plugin.json of 0.16.1 on this machine), not repository drift. The three
    sources compared here are all repository sources.
    If this fails, run: python3 scripts/sync_version.py"""
    plugin = _plugin_version()
    assert _pyproject_version() == plugin
    assert _init_version() == plugin


def test_sync_script_is_idempotent(tmp_path):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "sync_version.py")],
                       capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 0, r.stderr
    plugin = _plugin_version()
    assert _pyproject_version() == plugin
    assert _init_version() == plugin
