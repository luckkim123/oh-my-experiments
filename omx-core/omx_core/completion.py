"""omx_core.completion -- the run-completion verdict engine (design doc §4).

Computes whether a project's finished training runs carry the evaluation
artifacts its `run_completion` contract (omx_core.profile) requires. Pure
filesystem read -- no ssh, no network, no subprocess; `rc` is never consulted
(design §3: a finished run is one whose `finished` glob matches, full stop --
teardown crashes and early SystemExits both lie about rc). A later task's
`omx close-check` is the only place this becomes an exit code; this module
only computes the {state, runs, missing, subject_count, output_root, how} verdict.

The one state this design exists to keep distinct from `checked`-with-zero-
runs is `unreadable`: an output_root that cannot be listed -- at ANY depth,
not just its own top level -- must never silently present as "nothing to
grade, pass" (the same defect class 0.16.1 fixed in `omx wiki list`). A
run_completion block is also an opt-in signal: once a project has declared
one, a profile broken after that (e.g. output_root deleted from metrics.yaml)
must resolve to `unreadable` rather than raise -- the hook's standing
fail-open (D9) would otherwise turn that raise into a silent ALLOW.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from omx_core.omx_paths import OmxPaths
from omx_core.profile import load_profile_metrics, load_run_completion


def _no_contract() -> dict:
    return {"state": "no-contract", "runs": [], "missing": [], "subject_count": None,
            "output_root": None, "how": None}


def _unreadable(output_root_repr, how) -> dict:
    return {"state": "unreadable", "runs": [], "missing": [], "subject_count": None,
            "output_root": output_root_repr, "how": how}


def _first_file_match(dir_path: Path, pattern: str) -> Path | None:
    """First glob match under dir_path that is a FILE -- an empty placeholder
    directory sharing the pattern's name must not satisfy 'required'/'finished'."""
    return next((m for m in dir_path.glob(pattern) if m.is_file()), None)


def _assert_tree_readable(top: Path) -> None:
    """Walk the entire subtree under `top`, raising the underlying OSError on the
    first directory that cannot be listed.

    Path.glob() silently swallows PermissionError/OSError at ANY level of its own
    walk (it mirrors shell-glob semantics -- an unreadable directory contributes no
    matches instead of raising). Without this pre-check, an unreadable `runs/` dir,
    an unreadable individual run dir, or an unreadable `checkpoints/` subdir would
    each read as "nothing here, pass" instead of `unreadable`: "I could not
    determine whether this run finished" must never be spelled the same way as
    "this run did not finish" (design §4).
    """
    def _reraise(err: OSError) -> None:
        raise err
    for _ in os.walk(top, onerror=_reraise):
        pass


def evaluate_completion(root) -> dict:
    """Compute the run-completion verdict for `root` (design §4).

    Returns {"state", "runs", "missing", "subject_count", "output_root", "how"};
    state is one of no-contract | checked | incomplete | unreadable.
    """
    contract = load_run_completion(root)
    if contract is None:
        return _no_contract()

    paths = root if isinstance(root, OmxPaths) else OmxPaths(root=root)
    metrics = load_profile_metrics(paths)
    how = contract["how"]

    output_root_raw = metrics.get("output_root")
    if not isinstance(output_root_raw, str) or output_root_raw == "":
        # A run_completion block is the opt-in signal; a profile broken AFTER that
        # opt-in is a state the gate refuses, not an internal error to wave through.
        return _unreadable(
            f"metrics.yaml: output_root must be a non-empty string, got {output_root_raw!r}", how)
    output_root = Path(output_root_raw)
    if not output_root.is_absolute():
        output_root = paths.root / output_root  # output_root is caller-supplied, never derived (omx_paths.py:601-607)

    unreadable = _unreadable(str(output_root), how)

    try:
        if not output_root.is_dir():
            return unreadable
        _assert_tree_readable(output_root)
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
        "subject_count": len(subjects),  # run dirs that matched `runs` and survived `exclude` --
        "output_root": str(output_root),  # distinguishes "0 candidates" from "N candidates, 0 finished"
        "how": how,
    }
