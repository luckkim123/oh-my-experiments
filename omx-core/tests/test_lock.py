"""T1+T2: omx_core.lock — the generic fcntl mutex (extracted from with_wiki_lock)
and the session-keyed O_EXCL run lease (spec 2.1). The mutex serializes
state.json load-mutate-save critical sections; the lease guards CLI-invocation
ownership of a run (one-shot-CLI model, D-R4-3)."""
import json
import os
import threading
import time

import pytest

from omx_core.lock import with_file_lock
from omx_core.omx_paths import OmxError


def test_with_file_lock_runs_fn_and_returns(tmp_path):
    lock = tmp_path / ".lock"
    assert with_file_lock(lock, lambda: 42) == 42


def test_with_file_lock_creates_parent(tmp_path):
    lock = tmp_path / "nested" / "dir" / ".lock"
    assert with_file_lock(lock, lambda: "ok") == "ok"
    assert lock.parent.is_dir()


def test_with_file_lock_serializes_concurrent_writers(tmp_path):
    # Two threads each read-increment-write a counter file while holding the
    # lock. Without mutual exclusion the interleave loses increments; with it
    # the file ends at exactly 2 * N.
    lock = tmp_path / ".lock"
    counter = tmp_path / "counter"
    counter.write_text("0")
    N = 200

    def bump():
        def crit():
            v = int(counter.read_text())
            time.sleep(0)  # widen the race window
            counter.write_text(str(v + 1))
        for _ in range(N):
            with_file_lock(lock, crit)

    t1, t2 = threading.Thread(target=bump), threading.Thread(target=bump)
    t1.start(); t2.start(); t1.join(); t2.join()
    assert int(counter.read_text()) == 2 * N


def test_with_file_lock_timeout_loud_fails(tmp_path):
    # Hold the lock in a background thread, then a foreground acquire with a
    # tiny timeout must raise OmxError (never hang, never silently proceed).
    lock = tmp_path / ".lock"
    holding = threading.Event()
    release = threading.Event()

    def holder():
        def crit():
            holding.set()
            release.wait(timeout=5)
        with_file_lock(lock, crit)

    t = threading.Thread(target=holder)
    t.start()
    assert holding.wait(timeout=5)
    try:
        with pytest.raises(OmxError):
            with_file_lock(lock, lambda: "should not run", timeout_s=0.2, retry_s=0.02)
    finally:
        release.set()
        t.join()


def test_with_file_lock_releases_on_exception(tmp_path):
    # An exception inside fn must still release the lock (a leaked lock would
    # deadlock the very next acquire).
    lock = tmp_path / ".lock"

    def boom():
        raise ValueError("inside fn")

    with pytest.raises(ValueError):
        with_file_lock(lock, boom)
    # the lock is free again: a fresh acquire returns immediately
    assert with_file_lock(lock, lambda: "free") == "free"


# --- T2: omx_paths lease/lock/marker getters ---

from omx_core.omx_paths import OmxPaths


def test_loop_lock_path(tmp_path):
    p = OmxPaths(root=str(tmp_path))
    assert p.loop_lock("run1") == tmp_path / ".omx" / "runs" / "run1" / ".loop-lock"


def test_state_lock_path(tmp_path):
    p = OmxPaths(root=str(tmp_path))
    assert p.state_lock() == tmp_path / ".omx" / "state" / ".state-lock"


def test_loop_marker_path(tmp_path):
    p = OmxPaths(root=str(tmp_path))
    assert p.loop_marker_json("run1") == tmp_path / ".omx" / "runs" / "run1" / "loop-status.json"


# --- T2: run-lease primitives (spec 2.1 / 3) ---

from omx_core.lock import (
    LOCK_STALE_HOURS,
    acquire_run_lease,
    read_run_lease,
    release_run_lease,
)

AWARE_NOW = "2026-07-11T10:00:00+00:00"


def test_lock_stale_hours_default_is_2():
    assert LOCK_STALE_HOURS == 2


def test_acquire_writes_session_keyed_payload(tmp_path):
    p = OmxPaths(root=str(tmp_path))
    lease = acquire_run_lease(p, "run1", session_id="sess-A", now_iso=AWARE_NOW)
    assert lease["session_id"] == "sess-A"
    assert lease["armed_at"] == AWARE_NOW
    assert isinstance(lease["armed_by_pid"], int)
    # the lease file exists and round-trips
    on_disk = read_run_lease(p, "run1")
    assert on_disk["session_id"] == "sess-A"


def test_acquire_mkdirs_run_dir_when_absent(tmp_path):
    # arm can precede tree scaffolding — ENOENT on the parent is not a failure.
    p = OmxPaths(root=str(tmp_path))
    assert not p.run_dir("fresh").exists()
    acquire_run_lease(p, "fresh", session_id="s", now_iso=AWARE_NOW)
    assert p.loop_lock("fresh").is_file()


def test_acquire_young_other_session_loud_fails(tmp_path):
    p = OmxPaths(root=str(tmp_path))
    acquire_run_lease(p, "run1", session_id="sess-A", now_iso=AWARE_NOW)
    with pytest.raises(OmxError) as ei:
        acquire_run_lease(p, "run1", session_id="sess-B",
                          now_iso="2026-07-11T10:30:00+00:00")  # +30min, still young
    msg = str(ei.value)
    assert "sess-A" in msg and "run1" in msg  # names the owning session + run


def test_acquire_young_same_session_still_loud_fails(tmp_path):
    # arm-twice: even the SAME session cannot double-claim a young lease (the
    # arm_loop already-armed path surfaces here as a loud fail).
    p = OmxPaths(root=str(tmp_path))
    acquire_run_lease(p, "run1", session_id="sess-A", now_iso=AWARE_NOW)
    with pytest.raises(OmxError):
        acquire_run_lease(p, "run1", session_id="sess-A",
                          now_iso="2026-07-11T10:05:00+00:00")


def test_acquire_reaps_stale_lease(tmp_path):
    # A lease older than stale_hours is reaped and re-claimed by the new session.
    p = OmxPaths(root=str(tmp_path))
    acquire_run_lease(p, "run1", session_id="sess-old", now_iso="2026-07-11T00:00:00+00:00")
    lease = acquire_run_lease(p, "run1", session_id="sess-new",
                              now_iso="2026-07-11T10:00:00+00:00")  # +10h > 2h
    assert lease["session_id"] == "sess-new"
    assert read_run_lease(p, "run1")["session_id"] == "sess-new"


def test_acquire_corrupt_lease_uses_mtime_fallback(tmp_path):
    # A corrupt (unparseable) lease is a stale-CANDIDATE, never insta-reaped:
    # it is reaped only if its file mtime is older than stale_hours. A FRESH
    # corrupt lease (mtime = real now) must therefore still block. The mtime
    # fallback compares against the REAL clock (time.time()), so this holds
    # regardless of what fictional now_iso the caller injects.
    p = OmxPaths(root=str(tmp_path))
    p.run_dir("run1").mkdir(parents=True)
    p.loop_lock("run1").write_text("{not json")  # corrupt, real mtime = now
    with pytest.raises(OmxError):
        acquire_run_lease(p, "run1", session_id="s", now_iso=AWARE_NOW)


def test_acquire_wrong_typed_armed_at_uses_mtime_fallback(tmp_path):
    # A lease that is valid JSON but has a non-string armed_at (e.g. an int,
    # reachable via a foreign/hand-edited/future-writer-bug lease) is also a
    # corrupt lease by contract: it must degrade to the mtime fallback
    # (TypeError from fromisoformat), not crash with an uncaught traceback.
    p = OmxPaths(root=str(tmp_path))
    p.run_dir("run1").mkdir(parents=True)
    p.loop_lock("run1").write_text(
        json.dumps({"session_id": "x", "armed_at": 123, "armed_by_pid": 1}))
    with pytest.raises(OmxError):
        acquire_run_lease(p, "run1", session_id="s", now_iso=AWARE_NOW)


def test_acquire_old_corrupt_lease_is_reaped(tmp_path):
    # Backdate the corrupt lease's REAL mtime past stale_hours (os.utime) so the
    # mtime fallback (real-clock delta) actually measures ~(STALE+1)h of age and
    # reaps it. This exercises the fallback for the right reason — the outcome is
    # independent of the injected now_iso.
    import os
    p = OmxPaths(root=str(tmp_path))
    p.run_dir("run1").mkdir(parents=True)
    lock = p.loop_lock("run1")
    lock.write_text("{corrupt")
    old = time.time() - (LOCK_STALE_HOURS + 1) * 3600
    os.utime(lock, (old, old))
    lease = acquire_run_lease(p, "run1", session_id="s", now_iso=AWARE_NOW)
    assert lease["session_id"] == "s"


def test_acquire_retries_when_lease_vanishes_during_contended_read(tmp_path, monkeypatch):
    # Race: our O_EXCL create hits EEXIST, but a concurrent release_run_lease
    # (e.g. another thread's disarm) unlinks the lease before we read it back.
    # read_run_lease then returns None for a lease that no longer exists — this
    # must self-heal by retrying the create, not loud-fail with a confusing
    # "owned by session None" message.
    # (white-box: monkeypatches module-level read_run_lease to force the exact
    # interleaving — update alongside acquire_run_lease's internal retry shape.)
    import omx_core.lock as lock_mod

    p = OmxPaths(root=str(tmp_path))
    acquire_run_lease(p, "run1", session_id="sess-A", now_iso=AWARE_NOW)

    real_read = lock_mod.read_run_lease
    calls = {"n": 0}

    def fake_read(paths, run_id):
        calls["n"] += 1
        if calls["n"] == 1:
            # simulate the concurrent release winning the window
            release_run_lease(paths, run_id)
            return None
        return real_read(paths, run_id)

    monkeypatch.setattr(lock_mod, "read_run_lease", fake_read)

    lease = acquire_run_lease(p, "run1", session_id="sess-B",
                              now_iso="2026-07-11T10:05:00+00:00")
    assert lease["session_id"] == "sess-B"
    assert read_run_lease(p, "run1")["session_id"] == "sess-B"


def test_release_is_unconditional(tmp_path):
    p = OmxPaths(root=str(tmp_path))
    acquire_run_lease(p, "run1", session_id="sess-A", now_iso=AWARE_NOW)
    # a DIFFERENT process/session releases it — no owner check (D-R4-3 / critic C2)
    assert release_run_lease(p, "run1") == {"released": True}
    assert read_run_lease(p, "run1") is None


def test_release_unheld_returns_false(tmp_path):
    p = OmxPaths(root=str(tmp_path))
    assert release_run_lease(p, "run1") == {"released": False}


def test_read_run_lease_absent_is_none(tmp_path):
    p = OmxPaths(root=str(tmp_path))
    assert read_run_lease(p, "run1") is None
