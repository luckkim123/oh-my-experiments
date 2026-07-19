"""omx_core.doctor — read-only environment preflight (#19).

Skills call `omx doctor` as a step-0 check so a stale/missing install fails
actionably instead of as a raw shell error. Read-only: touches nothing.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import re
import sys
from pathlib import Path

_DEPS = ("numpy", "yaml", "matplotlib", "tensorboard", "pandas")

# Simple '>=X.Y' floor parser matching pyproject's requires-python (omx-3 fix):
# unsupported Python otherwise dies deep inside a PEP-604 `X | None` TypeError
# instead of an actionable doctor message.
_FLOOR_RE = re.compile(r">=\s*(\d+)\.(\d+)")


def _python_floor_ok(requires_python: str | None) -> bool | None:
    """True/False if requires_python is a parseable '>=X.Y' floor; else None
    (missing metadata or an unsupported specifier — never loud-fail doctor)."""
    if not requires_python:
        return None
    m = _FLOOR_RE.search(requires_python)
    if not m:
        return None
    return sys.version_info[:2] >= (int(m.group(1)), int(m.group(2)))


def run_doctor(root=None, plugin_root=None) -> dict:
    from omx_core.root import resolve_omx_root
    try:
        omx_version = importlib.metadata.version("omx-core")
        requires_python = importlib.metadata.metadata("omx-core").get("Requires-Python")
    except importlib.metadata.PackageNotFoundError:
        omx_version = None
        requires_python = None
    python_ok = _python_floor_ok(requires_python)
    if python_ok is False:
        python_check = (
            f"FAIL: running Python {sys.version.split()[0]}, omx-core requires "
            f"{requires_python} — upgrade your interpreter (e.g. pyenv/brew a "
            f"Python {requires_python} venv) and reinstall omx-core into it")
    elif python_ok is True:
        python_check = f"PASS: Python {sys.version.split()[0]} satisfies {requires_python}"
    else:
        python_check = "SKIP: requires-python floor unknown (package metadata unavailable)"
    resolved, stage = resolve_omx_root(explicit=root)
    profile_present = (Path(resolved) / ".omx" / "profile" / "metrics.yaml").exists()
    tree_yaml_present = (Path(resolved) / ".omx" / "profile" / "tree.yaml").exists()
    hooks_installed = None
    if plugin_root is not None:
        hooks_installed = (Path(plugin_root) / "hooks" / "run_hook.py").exists()
    return {
        "omx_version": omx_version,
        "python_version": sys.version.split()[0],
        "requires_python": requires_python,
        "python_ok": python_ok,
        "python_check": python_check,
        "omx_core_importable": True,  # we are running from it
        "deps": {name: importlib.util.find_spec(name) is not None for name in _DEPS},
        "resolved_root": str(resolved),
        "root_stage": stage,
        "profile_present": profile_present,
        "tree_yaml_present": tree_yaml_present,
        "hooks_installed": hooks_installed,
    }
