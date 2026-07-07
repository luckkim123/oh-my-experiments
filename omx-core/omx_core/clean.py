"""omx_core.clean — the review-gated cleanup ritual (#22, original design 10.3).

Classify inside .omx/ ONLY; dry-run by default; --apply moves SWEEP paths to
.omx/.trash/<ts>/ (recoverable, never rm). KEEP is implicit: only the named
SWEEP patterns are ever candidates, so profile/, registry/, campaigns/,
state.json and the run trio are untouchable by construction — and the
permanent output trees live outside .omx/, structurally unreachable."""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from omx_core.omx_paths import OmxError, OmxPaths


class CleanError(OmxError):
    """Loud-fail for cleanup misuse (bad scope/flags, missing .omx)."""


_SCOPES = ("session", "run", "all")


def _du(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for dp, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += (Path(dp) / f).stat().st_size
            except OSError:
                pass
    return total


def classify(paths: OmxPaths, *, scope, session_id=None, older_than_days=None,
             now=None) -> list:
    if scope not in _SCOPES:
        raise CleanError(f"--scope must be one of {_SCOPES}, got {scope!r}")
    now = time.time() if now is None else now
    omx = paths.omx_dir
    if not omx.is_dir():
        raise CleanError(f"no .omx/ at {omx}")

    def _old_enough(p: Path) -> bool:
        if older_than_days is None:
            return True
        return (now - p.stat().st_mtime) >= older_than_days * 86400

    sweep = []
    if scope in ("session", "all"):
        scratch = omx / "scratch"
        if scratch.is_dir():
            for sid in sorted(scratch.iterdir()):
                if not sid.is_dir():
                    continue
                if session_id is not None and sid.name != session_id:
                    continue
                if _old_enough(sid):
                    sweep.append((sid, "scratch (session-bound)"))
    if scope in ("run", "all"):
        runs = omx / "runs"
        if runs.is_dir():
            for cache in sorted(runs.glob("*/cache")):
                if cache.is_dir() and _old_enough(cache):
                    sweep.append((cache, "runs cache (re-derivable)"))
    if scope == "all":
        for tmp in sorted(omx.rglob("*.tmp*")):
            if ".trash" in tmp.parts:
                continue
            sweep.append((tmp, "orphaned tmp"))

    out = []
    for p, reason in sweep:
        p.resolve().relative_to(omx.resolve())  # ValueError here = a bug; loud
        out.append({"path": str(p), "bytes": _du(p), "reason": reason, "_p": p})
    return out


def apply_sweep(paths: OmxPaths, entries, *, trash_ts) -> dict:
    trash = paths.omx_dir / ".trash" / str(trash_ts)
    moved = []
    for e in entries:
        src = e["_p"]
        rel = src.relative_to(paths.omx_dir)
        dst = trash / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved.append(str(rel))
    return {"trash": str(trash), "moved": moved}


def purge_trash(paths: OmxPaths) -> dict:
    """The ONLY deleting function in this module; CLI double-flag gated."""
    trash = paths.omx_dir / ".trash"
    if not trash.is_dir():
        return {"purged": []}
    purged = [p.name for p in sorted(trash.iterdir())]
    shutil.rmtree(trash)
    return {"purged": purged}
