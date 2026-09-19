"""omx_core.completion -- the run-completion verdict engine (design doc §4).

Computes whether a project's finished training runs carry the evaluation
artifacts its `run_completion` contract (omx_core.profile) requires. Pure
filesystem read -- no ssh, no network, no subprocess; `rc` is never consulted
(design §3: a finished run is one whose `finished` glob matches, full stop --
teardown crashes and early SystemExits both lie about rc). A later task's
`omx close-check` is the only place this becomes an exit code; this module
only computes the {state, runs, missing, subject_count, output_root, how, reason}
verdict.

The one state this design exists to keep distinct from `checked`-with-zero-
runs is `unreadable`: an output_root that cannot be listed -- at ANY depth,
not just its own top level -- must never silently present as "nothing to
grade, pass" (the same defect class 0.16.1 fixed in `omx wiki list`).

The `run_completion` KEY is the opt-in signal, and it is a literal one: a
missing profile, an unparseable metrics.yaml, or a profile with no
run_completion key at all are three ways of saying "this project never opted
in" -- `no-contract`, allowed, silently. That must hold for every unrelated
project on the machine, not just ones that ran `exp-init`. Only once the key
is actually present does a broken profile become `unreadable` rather than
no-contract: a malformed run_completion block, or (once that block is valid)
an unusable/absent output_root, or an unreadable tree at any depth below it.
Conflating "never opted in" with "opted in and broken" -- which a single
`except OmxError` around the whole load once did -- would deny every project
on the machine that has nothing to do with omx. That is why the profile is
read and the key is checked BEFORE the one narrow try/except that can raise
`unreadable`, rather than wrapping the whole load in one catch. `reason`
names which cause fired and the offending path or key, since "could not read
the tree" and "the contract itself is broken" call for different next
actions.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from omx_core.omx_paths import OmxError, OmxPaths
from omx_core.profile import load_profile_metrics, validate_run_completion


def _no_contract() -> dict:
    return {"state": "no-contract", "runs": [], "missing": [], "subject_count": None,
            "output_root": None, "how": None, "reason": None}


def _unreadable(output_root_repr, how, reason) -> dict:
    return {"state": "unreadable", "runs": [], "missing": [], "subject_count": None,
            "output_root": output_root_repr, "how": how, "reason": reason}


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

    Returns {"state", "runs", "missing", "subject_count", "output_root", "how",
    "reason"}; state is one of no-contract | checked | incomplete | unreadable.
    """
    paths = root if isinstance(root, OmxPaths) else OmxPaths(root=root)

    try:
        metrics = load_profile_metrics(paths)
    except OmxError:
        # No profile at all (never ran exp-init), or metrics.yaml doesn't even parse
        # as a mapping -- nobody declared anything, so this is "no contract", not
        # "broken contract". The opt-in signal (a run_completion key) can only be
        # read from a profile that parses; a project unrelated to omx entirely --
        # or one that just hasn't been initialized yet -- must never be blocked
        # (success criterion 3). This is a DIFFERENT try than the one below: this one
        # is deliberately wide (any parse failure -> no-contract), the one below is
        # deliberately narrow (only the run_completion block itself -> unreadable).
        return _no_contract()

    block = metrics.get("run_completion")
    if block is None:
        return _no_contract()

    try:
        contract = validate_run_completion(block)
    except OmxError as err:
        # The run_completion key IS the opt-in signal; once it's there, a MALFORMED
        # block is a state the gate refuses, not an internal error to wave through --
        # the hook's fail-open (D9) would otherwise turn this raise into a silent
        # ALLOW on a project that declared a contract and then typoed it. This except
        # can fire for exactly one reason now (unlike wrapping load_run_completion,
        # which also raises for the two profile-absent/unparseable cases above).
        return _unreadable(None, None, reason=str(err))

    how = contract["how"]

    output_root_raw = metrics.get("output_root")
    if not isinstance(output_root_raw, str) or output_root_raw == "":
        # Same opt-in logic, second cause: output_root itself missing/invalid.
        return _unreadable(
            None, how,
            reason=f"metrics.yaml: output_root must be a non-empty string, got {output_root_raw!r}")
    output_root = Path(output_root_raw)
    if not output_root.is_absolute():
        output_root = paths.root / output_root  # output_root is caller-supplied, never derived (omx_paths.py:601-607)

    try:
        if not output_root.is_dir():
            return _unreadable(str(output_root), how, reason=f"output_root is not a directory: {output_root}")
        _assert_tree_readable(output_root)
        run_dirs = sorted(p for p in output_root.glob(contract["runs"]) if p.is_dir())
    except OSError as err:
        detail = f"{err.filename}: {err.strerror}" if err.filename and err.strerror else str(err)
        return _unreadable(str(output_root), how, reason=f"cannot list {detail}")

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
        "reason": None,
    }
