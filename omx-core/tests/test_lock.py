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
