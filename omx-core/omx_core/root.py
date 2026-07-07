"""omx_core.root — the 5-stage .omx anchor resolution ladder (#13).

Order: explicit --root > $OMX_STATE_DIR/<project_id> > .omx-workspace marker
(climb, stop before $HOME) > git toplevel > cwd. Placement/identity split:
project_id hashes the git origin remote (or the toplevel's absolute path) and
never climbs submodules — two worktrees of one repo share one identity.
Kill switch: OMX_NO_ROOT_LADDER=1 collapses to explicit-else-cwd (D9 spirit).
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

MARKER = ".omx-workspace"


def _git(args: list, cwd: Path) -> str | None:
    try:
        out = subprocess.check_output(["git", *args], cwd=str(cwd),
                                      stderr=subprocess.DEVNULL)
        return out.decode().strip() or None
    except (subprocess.CalledProcessError, OSError):
        return None


def project_id(toplevel: Path, remote: str | None) -> str:
    """`<basename>-<sha256(identity)[:16]>`; identity = remote URL else abs path."""
    identity = remote or str(Path(toplevel).resolve())
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{Path(toplevel).name}-{digest}"


def resolve_omx_root(explicit=None, *, cwd=None, env=None) -> tuple[Path, str]:
    """Resolve the .omx anchor; returns (root, stage). Never raises."""
    env = os.environ if env is None else env
    cwd = Path.cwd() if cwd is None else Path(cwd)
    if explicit:
        return Path(explicit), "explicit"
    if env.get("OMX_NO_ROOT_LADDER") == "1":
        return cwd, "cwd"
    state_dir = env.get("OMX_STATE_DIR")
    if state_dir:
        top_s = _git(["rev-parse", "--show-toplevel"], cwd)
        top = Path(top_s) if top_s else cwd
        remote = _git(["remote", "get-url", "origin"], top)
        return Path(state_dir) / project_id(top, remote), "state-dir"
    home = Path.home()
    node = cwd.resolve()
    while node != node.parent and node != home:
        if (node / MARKER).exists():
            return node, "marker"
        node = node.parent
    top_s = _git(["rev-parse", "--show-toplevel"], cwd)
    if top_s:
        return Path(top_s), "git"
    return cwd, "cwd"
