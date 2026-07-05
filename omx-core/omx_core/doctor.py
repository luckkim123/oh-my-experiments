"""omx_core.doctor — read-only environment preflight (#19).

Skills call `omx doctor` as a step-0 check so a stale/missing install fails
actionably instead of as a raw shell error. Read-only: touches nothing.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import sys
from pathlib import Path

_DEPS = ("numpy", "yaml", "matplotlib", "tensorboard", "pandas")


def run_doctor(root=None, plugin_root=None) -> dict:
    try:
        omx_version = importlib.metadata.version("omx-core")
    except importlib.metadata.PackageNotFoundError:
        omx_version = None
    profile_present = None
    if root is not None:
        profile_present = (Path(root) / ".omx" / "profile" / "metrics.yaml").exists()
    hooks_installed = None
    if plugin_root is not None:
        hooks_installed = (Path(plugin_root) / "hooks" / "run_hook.py").exists()
    return {
        "omx_version": omx_version,
        "python_version": sys.version.split()[0],
        "omx_core_importable": True,  # we are running from it
        "deps": {name: importlib.util.find_spec(name) is not None for name in _DEPS},
        "profile_present": profile_present,
        "hooks_installed": hooks_installed,
    }
