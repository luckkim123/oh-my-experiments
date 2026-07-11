"""omx_core.lock — file locking primitives.

Two locks, two jobs (D-R4-3, spec 2.1):
  - with_file_lock: a generic fcntl mutex (extracted verbatim from
    wiki/storage.with_wiki_lock, WikiError -> OmxError). Serializes every
    state.json load-mutate-save critical section so two concurrent loop_gate
    increments cannot last-write-win. All wiki writes still go through it via
    the with_wiki_lock delegate.
  - acquire_run_lease / release_run_lease / read_run_lease (added in T2): a
    per-run O_EXCL lease keyed by the omx SESSION id (not pid — omx is a
    one-shot-CLI architecture where no process spans the loop, so a recorded
    pid is dead before any assertion runs). Reaped on AGE alone.
"""
from __future__ import annotations

import fcntl
import time
from pathlib import Path

from omx_core.omx_paths import OmxError


def with_file_lock(lock_path, fn, *, timeout_s: float = 5.0, retry_s: float = 0.05):
    """Run `fn` while holding an exclusive fcntl lock on `lock_path`.

    The generic mutex behind every serialized critical section (state.json
    writes, wiki writes). Loud-fail (OmxError) if the lock cannot be acquired
    within `timeout_s`. The lock is released in a finally, so an exception in
    `fn` never leaks the lock (which would deadlock the next acquire)."""
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    with open(lock_path, "a", encoding="utf-8") as fh:
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise OmxError(
                        f"file lock busy after {timeout_s}s ({lock_path}); "
                        "another process holds it")
                time.sleep(retry_s)
        try:
            return fn()
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


import json
import os
from datetime import datetime

LOCK_STALE_HOURS = 2  # a lease older than this (by armed_at, mtime fallback) is reaped


def _lease_age_hours(lease: dict | None, lock_path: Path, now_iso: str) -> float:
    """Age of the lease in hours. Prefer armed_at (the recorded claim instant);
    fall back to the file mtime when the lease JSON is corrupt/missing armed_at
    (a corrupt lease is a stale-CANDIDATE, never insta-reaped)."""
    armed_at = (lease or {}).get("armed_at")
    if armed_at:
        try:
            armed_dt = datetime.fromisoformat(armed_at)
            now_dt = datetime.fromisoformat(now_iso)
            if (armed_dt.tzinfo is None) == (now_dt.tzinfo is None):
                return (now_dt - armed_dt).total_seconds() / 3600.0
        except (ValueError, TypeError):
            pass
    # mtime fallback (corrupt lease, or armed_at/now tz mismatch): mtime is a
    # REAL-clock timestamp, so it must be compared against the real clock
    # (time.time()) — NOT the caller-injected now_iso, which is only valid for
    # comparing against the lease's recorded armed_at. Mixing the two contaminates
    # the age with the gap between real-now and any fictional injected now_iso.
    try:
        mtime = lock_path.stat().st_mtime
    except OSError:
        return 0.0  # gone under us -> treat as young; the O_EXCL retry will decide
    return (time.time() - mtime) / 3600.0


def _write_lease(lock_path: Path, payload: dict) -> None:
    """O_CREAT|O_EXCL|O_WRONLY write — creation IS the atomic claim. Raises
    FileExistsError when the lease already exists (the caller reaps-or-fails)."""
    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, json.dumps(payload, sort_keys=True).encode("utf-8"))
    finally:
        os.close(fd)


def read_run_lease(paths, run_id) -> dict | None:
    """Return the lease dict, or None if absent. Corrupt JSON -> None (the
    caller treats a corrupt lease as a stale-candidate via mtime, not a claim)."""
    lock_path = paths.loop_lock(run_id)
    if not lock_path.exists():
        return None
    try:
        return json.loads(lock_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def acquire_run_lease(paths, run_id, *, session_id, now_iso,
                      stale_hours: float = LOCK_STALE_HOURS) -> dict:
    """Claim runs/<run_id>/.loop-lock via O_EXCL, keyed by the omx session id.

    Payload {session_id, armed_at, armed_by_pid} — armed_by_pid is FORENSIC
    ONLY, never read for a decision (one-shot-CLI model, D-R4-3). On EEXIST:
    reap iff the existing lease is older than stale_hours (by armed_at, mtime
    fallback for a corrupt lease), else loud-fail naming the owning session.
    Reaping unlinks and retries O_EXCL once; an ENOENT on that unlink means
    another reaper won -> retry O_EXCL once (reaper race); losing the re-create
    race loud-fails as 'run owned'."""
    lock_path = paths.loop_lock(run_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)  # arm can precede scaffolding
    payload = {"session_id": session_id, "armed_at": now_iso, "armed_by_pid": os.getpid()}
    try:
        _write_lease(lock_path, payload)
        return payload
    except FileExistsError:
        pass
    # contended: reap-or-fail
    existing = read_run_lease(paths, run_id)
    if existing is None:
        # the lease vanished between our EEXIST and this read (e.g. a
        # concurrent release_run_lease/disarm won the narrow window) — there
        # is nothing to reap or report as "owned"; retry the create once,
        # same as the reaper-race retry below.
        try:
            _write_lease(lock_path, payload)
            return payload
        except FileExistsError:
            existing = read_run_lease(paths, run_id)
    age = _lease_age_hours(existing, lock_path, now_iso)
    if age <= stale_hours:
        owner = (existing or {}).get("session_id")
        armed = (existing or {}).get("armed_at")
        raise OmxError(
            f"run {run_id!r} is owned by loop session {owner!r} (armed {armed}); "
            "disarm it (`omx loop-disarm`) or wait for the lease to go stale "
            f"(> {stale_hours}h).")
    # stale -> reap (unlink) and re-claim, tolerating a concurrent reaper
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass  # another reaper won the unlink — just try to re-create below
    try:
        _write_lease(lock_path, payload)
        return payload
    except FileExistsError:
        winner = read_run_lease(paths, run_id)
        raise OmxError(
            f"run {run_id!r} lease re-claimed concurrently by "
            f"{(winner or {}).get('session_id')!r}; retry or disarm.")


def release_run_lease(paths, run_id) -> dict:
    """Unlink the lease UNCONDITIONALLY (no owner check). Whichever process
    disarms is authoritatively ending the loop (critic C2: this is what lets a
    gate self-disarm clean up a lease it does not 'own' by pid). Releasing an
    unheld lease returns {'released': False}, never raises."""
    lock_path = paths.loop_lock(run_id)
    try:
        lock_path.unlink()
        return {"released": True}
    except FileNotFoundError:
        return {"released": False}
