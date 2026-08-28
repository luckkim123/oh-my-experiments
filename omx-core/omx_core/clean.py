"""omx_core.clean — the review-gated cleanup ritual (#22, original design 10.3).

Classify inside a SINGLE resolved store ONLY; dry-run by default; --apply
moves SWEEP paths to <resolved>/.trash/<ts>/ (recoverable, never rm). KEEP is
implicit: only the named SWEEP patterns are ever candidates, so profile/,
registry/(wiki), campaigns/, state.json and the run trio are untouchable by
construction — and the permanent output trees live outside the store,
structurally unreachable.

.hq/ cutover: unlike list_campaigns()/list_programs()/loop-status --all
(campaign.py, cli.py), clean NEVER unions the two stores and never reaches
into legacy once a project is anchored. store-spec §7 says the legacy store
is not deleted, trashed, or git-rm'ed until a separate `purge` release — a
sweep that moved legacy content into .trash (or a purge that rmtree'd it)
would violate that fallback contract before its window has even closed. So a
sweep operates on a single locus, chosen by anchor state, never both:
unanchored -> the flat legacy .omx/ tree (unchanged from before this port);
anchored -> the whole new .hq/ tree (scratch under runtime/experiments/,
runs under work/experiments/ — different top-level subtrees now, unlike
legacy's flat layout, so 'the resolved tree' for the orphaned-.tmp* rglob is
all of .hq/, not one layer). .trash itself follows the same single-locus
rule via OmxPaths.trash_root() (_write()-resolved like every other getter):
runtime/experiments/trash/ for an anchored project — ephemeral, regenerated
per sweep, matching the layer rules' 'loss harmless' condition, same class
as other runtime/ state. This matters beyond tidiness: trash_root() staying
on .omx/ unconditionally would mean the first `clean --apply` after a
`--purge` on an anchored project recreates .omx/.trash and silently undoes
the purge — resolving it the same way as every entity getter closes that."""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from omx_core.omx_paths import HQ_ROOT, OmxError, OmxPaths, has_anchor, runtime_dir, work_dir


class CleanError(OmxError):
    """Loud-fail for cleanup misuse (bad scope/flags, missing store)."""


_SCOPES = ("session", "run", "all")


def _clean_roots(paths: OmxPaths) -> dict:
    """{'base', 'scratch', 'runs', 'trash'} — the SINGLE tree clean.py
    operates on for this project. See module docstring: never both stores.
    'trash' comes from OmxPaths.trash_root() (its own _write()-resolved
    getter), not computed inline here — that is what keeps a purge+clean
    cycle from ever landing trash back on .omx/ once anchored."""
    if has_anchor(paths.root):
        return {
            "base": Path(paths.root) / HQ_ROOT,
            "scratch": runtime_dir(paths.root) / "scratch",
            "runs": work_dir(paths.root) / "runs",
            "trash": paths.trash_root(),
        }
    base = paths.omx_dir
    return {"base": base, "scratch": base / "scratch", "runs": base / "runs",
           "trash": paths.trash_root()}


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
    roots = _clean_roots(paths)
    base = roots["base"]
    if not base.is_dir():
        raise CleanError(f"no store at {base}")

    def _old_enough(p: Path) -> bool:
        if older_than_days is None:
            return True
        return (now - p.stat().st_mtime) >= older_than_days * 86400

    sweep = []
    if scope in ("session", "all"):
        scratch = roots["scratch"]
        if scratch.is_dir():
            for sid in sorted(scratch.iterdir()):
                if not sid.is_dir():
                    continue
                if session_id is not None and sid.name != session_id:
                    continue
                if _old_enough(sid):
                    sweep.append((sid, "scratch (session-bound)"))
    if scope in ("run", "all"):
        runs = roots["runs"]
        if runs.is_dir():
            for cache in sorted(runs.glob("*/cache")):
                if cache.is_dir() and _old_enough(cache):
                    sweep.append((cache, "runs cache (re-derivable)"))
    if scope == "all":
        trash_root = roots["trash"]
        for tmp in sorted(base.rglob("*.tmp*")):
            # path-based, not a ".trash" name-string match: the new store's
            # trash_root() is named "trash" (no leading dot, since the whole
            # runtime/ layer is already .gitignore'd), so a hardcoded ".trash"
            # part-name check would silently stop excluding it and re-sweep
            # trash's own contents as "orphaned tmp".
            if trash_root in tmp.parents:
                continue
            sweep.append((tmp, "orphaned tmp"))

    out = []
    for p, reason in sweep:
        p.resolve().relative_to(base.resolve())  # ValueError here = a bug; loud
        out.append({"path": str(p), "bytes": _du(p), "reason": reason, "_p": p})
    return out


def apply_sweep(paths: OmxPaths, entries, *, trash_ts) -> dict:
    roots = _clean_roots(paths)
    trash = roots["trash"] / str(trash_ts)
    moved = []
    for e in entries:
        src = e["_p"]
        rel = src.relative_to(roots["base"])
        dst = trash / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved.append(str(rel))
    return {"trash": str(trash), "moved": moved}


def purge_trash(paths: OmxPaths) -> dict:
    """The ONLY deleting function in this module; CLI double-flag gated."""
    trash = _clean_roots(paths)["trash"]
    if not trash.is_dir():
        return {"purged": []}
    purged = [p.name for p in sorted(trash.iterdir())]
    shutil.rmtree(trash)
    return {"purged": purged}
