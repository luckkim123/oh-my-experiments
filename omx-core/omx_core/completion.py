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
import importlib.metadata
import json
import os
import warnings
from datetime import timedelta
from pathlib import Path

from omx_core.atomic import atomic_path
from omx_core.clock import parse_iso_utc
from omx_core.omx_paths import OmxError, OmxPaths, has_anchor, runtime_dir
from omx_core.profile import load_profile_metrics, validate_run_completion

# design §5: clock skew tolerance for a receipt/defer instant reported as
# slightly in the future -- anything beyond this is treated as bogus, not aged.
_CLOCK_SKEW_TOLERANCE = timedelta(minutes=1)


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


# --- completion-gate memory (design §5) -------------------------------------
#
# Two separate files under the runtime layer, not one: a receipt (a computed
# verdict) and a defer (a human's recorded decision to close anyway) answer
# different questions, and a defer must survive a new receipt being written.
#
# Path resolution mirrors hooks/handlers.py:compact_breadcrumb exactly --
# anchor-gated, never a per-file fallback: an anchored project resolves under
# `.hq/runtime/experiments/`, a legacy one under `.omx/`.

_RECEIPT_NAME = "completion-receipt.json"
_DEFER_NAME = "completion-defer.json"


def _completion_dir(paths: OmxPaths) -> Path:
    return runtime_dir(paths.root) if has_anchor(paths.root) else paths.omx_dir


def _read_json(target: Path) -> dict | None:
    """dict on success; None for anything else (missing, unreadable, undecodable,
    not JSON, not an object) -- corrupt on-disk state must read the same as
    absent state, never raise. A genuinely missing file is silent; a file that
    EXISTS but can't be read as UTF-8 (permission denied, or bytes that aren't
    valid UTF-8 -- UnicodeDecodeError is a ValueError, not an OSError, so it
    needs its own arm) is distinguished with a warning, since "could not read"
    and "not there" are exactly the two states this whole module exists to
    keep apart -- the caller's contract (None either way, never raise) does
    not change."""
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as err:
        warnings.warn(f"{target}: exists but unreadable: {err}", RuntimeWarning, stacklevel=2)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _same_root(receipt_root, expected_root) -> bool:
    """True when `receipt_root` (the value that crossed a boundary as text,
    untrusted) names the same filesystem path as `expected_root` (supplied by
    the calling code from its own OmxPaths, trusted).

    Tolerant of a trailing separator, a redundant './' segment, or a symlink
    to the same tree (finding 5) -- both sides are compared via
    `Path.resolve()`, which does not require the path to exist (strict=False
    is the default), since a receipt legitimately outlives the tree it was
    written for.

    `receipt_root` must additionally be a non-empty ABSOLUTE path BEFORE
    resolving, or this returns False outright (finding 6): `Path("").resolve()`
    and `Path(".").resolve()` both silently return the current working
    directory, which would let an empty/dot/relative receipt root satisfy
    whatever project the session happens to be sitting in -- resolving is what
    manufactures that false identity, so the check runs before it, and only
    on the untrusted side. `write_receipt` always writes an absolute root, so
    this never rejects a receipt this module itself produced; `expected_root`
    gets no such restriction since it is caller-supplied and may legitimately
    be relative.

    Also tolerant of `receipt_root`/`expected_root` being the wrong TYPE
    entirely (a number, a list, absent -- plain `!=` absorbed that for free;
    `Path()` does not, so it is caught here explicitly rather than silently
    disappearing), and of a `receipt_root` that IS string-like but not a
    legal path: a `TypeError` from `Path()` (finding 6) is only one member of
    the exception family this can raise -- an embedded NUL byte is a
    `ValueError` raised by `.resolve()` itself, not by construction (finding
    7; measured: `Path("/tmp/\\x00bad")` builds fine, `.resolve()` is what
    raises `lstat: embedded null character in path`), and `.resolve()` can
    also raise `OSError` on some platforms for a path past the OS length
    limit. One `try` around the whole comparison, catching all three, rather
    than a narrower catch re-justified against whatever the tests happened to
    exercise."""
    try:
        receipt_path = Path(receipt_root)
        return receipt_path.is_absolute() and receipt_path.resolve() == Path(expected_root).resolve()
    except (TypeError, ValueError, OSError):
        return False


def _fresh(instant, now, max_age_h: float) -> bool:
    """True when `instant` is no more than `max_age_h` hours older than `now`,
    and not more than _CLOCK_SKEW_TOLERANCE in `now`'s future -- a receipt/defer
    reported to be hours or days ahead of now is bogus, not merely young, and
    must not satisfy just because a naive age check would compute it negative."""
    age = now - instant
    return -_CLOCK_SKEW_TOLERANCE <= age <= timedelta(hours=max_age_h)


def write_receipt(paths: OmxPaths, verdict: dict, *, source: str, now_iso: str) -> None:
    """Record a computed run-completion verdict (design §5). `source` is
    "local" (computed where the hook runs) or "remote" (carried back across
    an ssh boundary by a later task's `omx close-ack`) -- it is the only
    reason this receipt distinguishes the two, and it is what lets
    `receipt_satisfies` know whether `root` is checkable at all.

    Serialized on `paths.state_lock()`, same coarser-lock discipline every
    other `atomic_path` writer in this repo uses (ledger.py, loop.py) --
    `atomic_path`'s fixed '.tmp' name is only crash-safe against a SINGLE
    writer at a time."""
    try:
        omx_version = importlib.metadata.version("omx-core")
    except importlib.metadata.PackageNotFoundError:
        omx_version = "unknown"
    receipt = {
        "checked_at": now_iso,
        "root": str(paths.root),
        "state": verdict["state"],
        "runs_checked": len(verdict["runs"]),
        "omx_version": omx_version,
        "source": source,
    }

    def _write() -> None:
        with atomic_path(_completion_dir(paths) / _RECEIPT_NAME) as tmp:
            tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True))

    from omx_core.lock import with_file_lock
    with_file_lock(paths.state_lock(), _write)


def read_receipt(paths: OmxPaths) -> dict | None:
    """The stored receipt, or None if absent or corrupt -- never raises."""
    return _read_json(_completion_dir(paths) / _RECEIPT_NAME)


def receipt_satisfies(receipt: dict | None, now_iso: str, max_age_h: float = 12,
                       *, expected_root) -> bool:
    """Whether `receipt` lets the gate pass right now.

    A non-"checked" state never satisfies at any age -- acking a failure is the
    exact bypass this mechanism exists to prevent. An unparseable or
    future-dated checked_at is treated as not satisfying rather than raised.

    `expected_root` is required, not optional: a `source == "local"` receipt
    (computed and stored for the SAME project by `close-check --record`) must
    resolve to the same path as `expected_root` (compared via `Path.resolve()`,
    not string equality -- a trailing separator, a `./` segment, a relative
    path, or a symlink to the same tree must all still match), or it does not
    satisfy -- otherwise a receipt file copied from an unrelated project's
    store would satisfy the gate for this one. A `source == "remote"` receipt
    legitimately names a different root (the far side of the ssh boundary the
    design crosses in §5) and is trusted without that check, the same
    deliberate-human-act trust `close-defer` gets. A missing or unrecognized
    `source` never satisfies."""
    if not isinstance(receipt, dict) or receipt.get("state") != "checked":
        return False
    source = receipt.get("source")
    if source == "local":
        if not _same_root(receipt.get("root"), expected_root):
            return False
    elif source != "remote":
        return False
    try:
        checked_at = parse_iso_utc(receipt.get("checked_at"), "receipt checked_at")
        now = parse_iso_utc(now_iso, "now")
    except OmxError:
        return False
    return _fresh(checked_at, now, max_age_h)


def write_defer(paths: OmxPaths, reason: str, now_iso: str) -> None:
    """Record a human's decision to close despite an incomplete/unreadable
    verdict. An empty or whitespace-only reason is refused -- the reason is
    the entire difference between a recorded escape and a silent one.

    Serialized on `paths.state_lock()` -- see `write_receipt`'s docstring."""
    if not isinstance(reason, str) or not reason.strip():
        raise OmxError("close-defer requires a non-empty reason")
    defer = {"deferred_at": now_iso, "reason": reason}

    def _write() -> None:
        with atomic_path(_completion_dir(paths) / _DEFER_NAME) as tmp:
            tmp.write_text(json.dumps(defer, indent=2, sort_keys=True))

    from omx_core.lock import with_file_lock
    with_file_lock(paths.state_lock(), _write)


def active_defer(paths: OmxPaths, now_iso: str, ttl_h: float = 12) -> bool:
    """Whether a still-live defer exists for `paths`. Missing, corrupt, or
    expired all read as False -- never raises."""
    data = _read_json(_completion_dir(paths) / _DEFER_NAME)
    if data is None:
        return False
    try:
        deferred_at = parse_iso_utc(data.get("deferred_at"), "defer deferred_at")
        now = parse_iso_utc(now_iso, "now")
    except OmxError:
        return False
    return _fresh(deferred_at, now, ttl_h)
