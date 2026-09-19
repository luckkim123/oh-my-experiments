"""omx_core.completion -- the run-completion verdict engine (design doc §4).

Computes whether a project's finished training runs carry the evaluation
artifacts its `run_completion` contract (omx_core.profile) requires. Pure
filesystem read -- no ssh, no network, no subprocess; `rc` is never consulted
(design §3: a finished run is one whose `finished` glob matches, full stop --
teardown crashes and early SystemExits both lie about rc). A later task's
`omx close-check` is the only place this becomes an exit code; this module
only computes the {state, runs, missing, output_root, how} verdict.

The one state this design exists to keep distinct from `checked`-with-zero-
runs is `unreadable`: an output_root that cannot be listed must never
silently present as "nothing to grade, pass" (the same defect class 0.16.1
fixed in `omx wiki list`).
"""
from __future__ import annotations

import fnmatch
from pathlib import Path

from omx_core.omx_paths import OmxError, OmxPaths
from omx_core.profile import load_profile_metrics, load_run_completion

_NO_CONTRACT = {"state": "no-contract", "runs": [], "missing": [], "output_root": None, "how": None}


def _first_file_match(dir_path: Path, pattern: str) -> Path | None:
    """First glob match under dir_path that is a FILE -- an empty placeholder
    directory sharing the pattern's name must not satisfy 'required'/'finished'."""
    return next((m for m in dir_path.glob(pattern) if m.is_file()), None)


def evaluate_completion(root) -> dict:
    """Compute the run-completion verdict for `root` (design §4).

    Returns {"state", "runs", "missing", "output_root", "how"}; state is one of
    no-contract | checked | incomplete | unreadable.
    """
    contract = load_run_completion(root)
    if contract is None:
        return dict(_NO_CONTRACT)

    paths = root if isinstance(root, OmxPaths) else OmxPaths(root=root)
    metrics = load_profile_metrics(paths)
    output_root_raw = metrics.get("output_root")
    if not isinstance(output_root_raw, str) or output_root_raw == "":
        raise OmxError("metrics.yaml: output_root must be a non-empty string")
    output_root = Path(output_root_raw)
    if not output_root.is_absolute():
        output_root = paths.root / output_root  # output_root is caller-supplied, never derived (omx_paths.py:601-607)

    how = contract["how"]
    unreadable = {"state": "unreadable", "runs": [], "missing": [], "output_root": str(output_root), "how": how}

    try:
        if not output_root.is_dir():
            return unreadable
        # Path.glob() silently swallows PermissionError per-directory (mirrors shell glob
        # semantics) -- probing with iterdir() first is the only way to actually surface it,
        # since this branch must never be reachable by returning zero runs instead (design §4).
        next(output_root.iterdir(), None)
        run_dirs = sorted(p for p in output_root.glob(contract["runs"]) if p.is_dir())
    except OSError:
        return unreadable

    exclude = contract.get("exclude") or []
    subjects = [
        run_dir for run_dir in run_dirs
        if not any(
            fnmatch.fnmatchcase(run_dir.relative_to(output_root).as_posix(), pattern)
            for pattern in exclude
        )
    ]

    finished = [
        run_dir for run_dir in subjects
        if _first_file_match(run_dir, contract["finished"]) is not None
    ]

    missing = []
    for run_dir in finished:
        rel = run_dir.relative_to(output_root).as_posix()
        misses = [g for g in contract["required"] if _first_file_match(run_dir, g) is None]
        if misses:
            missing.append({"run": rel, "missing": misses, "how": how.replace("{run}", rel)})

    return {
        "state": "incomplete" if missing else "checked",
        "runs": [run_dir.relative_to(output_root).as_posix() for run_dir in finished],
        "missing": missing,
        "output_root": str(output_root),
        "how": how,
    }
