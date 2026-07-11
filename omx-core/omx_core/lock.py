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
