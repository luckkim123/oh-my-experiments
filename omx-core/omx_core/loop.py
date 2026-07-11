"""omx_core.loop — exp-loop's Claude-free core: a max-runtime deadline ceiling
and the pending-launch queue. NO launch execution lives here (design D4/B8):
exp-loop queues the next training launch for human approval and never fires it.

The deadline helpers are PURE and time-INJECTED — the caller passes the current
instant as an ISO-8601 string, so unit tests are deterministic and the functions
never read the wall clock. Only the CLI layer (cli.py _cmd_loop_status) reads the
real clock. This mirrors OMC runtime.ts:971-972 (deadlineAt = now + maxRuntimeMs)
and persistent-mode/index.ts:1463-1474 (deadline check), re-implemented, never
imported.
"""
import json
from datetime import datetime, timedelta

from omx_core.omx_paths import OmxError, OmxPaths, atomic_path


def _parse_iso(value, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise OmxError(f"{label} must be a non-empty ISO-8601 string, got {value!r}.")
    try:
        return datetime.fromisoformat(value)
    except ValueError as e:
        raise OmxError(f"{label} is not a valid ISO-8601 timestamp: {value!r}.") from e


def compute_deadline(now_iso: str, max_runtime_s: int) -> str:
    """Return the ISO-8601 instant `max_runtime_s` seconds after `now_iso`.

    This is the analyze/design/eval ceiling — NOT a launch trigger (D4/B8).
    Loud-fail on a non-positive runtime or an unparseable `now_iso`.
    """
    if not isinstance(max_runtime_s, int) or isinstance(max_runtime_s, bool) or max_runtime_s <= 0:
        raise OmxError(f"max_runtime_s must be a positive int, got {max_runtime_s!r}.")
    start = _parse_iso(now_iso, "now_iso")
    return (start + timedelta(seconds=max_runtime_s)).isoformat()


def deadline_passed(deadline_iso: str, now_iso: str) -> bool:
    """True iff `now_iso` is at or past `deadline_iso` (the ceiling is inclusive).

    Both args are loud-fail-parsed. exp-loop calls this between iterations to
    decide whether to stop the autonomous analyze/design/eval phase. The two
    timestamps must agree on timezone-awareness (both aware or both naive); a
    naive-vs-aware mix loud-fails (OmxError) rather than raising a raw TypeError
    or silently assuming a timezone.
    """
    deadline = _parse_iso(deadline_iso, "deadline_iso")
    now = _parse_iso(now_iso, "now_iso")
    if (deadline.tzinfo is None) != (now.tzinfo is None):
        raise OmxError(
            "deadline_iso and now_iso must both be timezone-aware or both naive; "
            f"got deadline={deadline_iso!r}, now={now_iso!r}.")
    return now >= deadline


def _require_nonempty(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OmxError(f"{label} must be a non-empty string, got {value!r}.")
    return value.strip()


def queue_pending_launch(paths: OmxPaths, run_id, *, proposal_id, launch_delta,
                         gpu_gate, queued_at) -> None:
    """Write runs/<run_id>/pending-launch.json marked 'pending approval' (B8).

    This is the ONLY thing exp-loop does with a launch — it queues it, never
    fires it. `proposal_id` ties back to the exp-design proposal; `launch_delta`
    is the one-line change vs the profile's launch.sh; `gpu_gate` is the
    nvidia-smi precondition the human must confirm; `queued_at` is an ISO-8601
    instant supplied by the caller (the CLI injects the real clock). All four
    are required and loud-fail when empty. Atomic write via atomic_path.
    """
    pid = _require_nonempty(proposal_id, "proposal_id")
    delta = _require_nonempty(launch_delta, "launch_delta")
    gate = _require_nonempty(gpu_gate, "gpu_gate")
    when = _require_nonempty(queued_at, "queued_at")
    target = paths.pending_launch_json(run_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "status": "pending approval",
        "proposal_id": pid,
        "launch_delta": delta,
        "gpu_gate": gate,
        "queued_at": when,
    }
    with atomic_path(target) as tmp:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))


def read_pending_launch(paths: OmxPaths, run_id):
    """Return the queued pending-launch dict, or None if nothing is queued.

    Loud-fail (OmxError) if the file exists but is not valid JSON — a corrupt
    queue must surface, never be silently treated as 'empty'."""
    target = paths.pending_launch_json(run_id)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text())
    except ValueError as e:
        raise OmxError(f"pending-launch.json for {run_id!r} is corrupt: {e}") from e


LOOP_HARD_CAP_DEFAULT = 50


def arm_loop(paths: OmxPaths, *, run_id, now_iso, max_runtime_s,
             hard_cap=LOOP_HARD_CAP_DEFAULT, session_id=None) -> dict:
    """Arm the Stop-hook loop gate (spec 2.4 + R4 #1). ONE loop per root; arming
    while armed loud-fails. The whole load->check-armed->lease->write runs under
    the state-file mutex so two concurrent arms cannot race (D-R4-3). A
    per-run O_EXCL lease keyed by `session_id` is acquired inside the lock; if
    the subsequent state write fails, the lease is released (try/finally). Any
    stale completion marker for this run is unlinked (a re-arm = a fresh loop).
    `max_runtime_s` is MANDATORY (an armed gate always self-expires); `now_iso`
    is the caller-injected AWARE UTC clock (naive/aware mixes make
    deadline_passed loud-fail, silently failing the gate open)."""
    from omx_core.lock import acquire_run_lease, release_run_lease, with_file_lock
    from omx_core.state import load_state, save_state
    rid = _require_nonempty(run_id, "run_id")
    if not isinstance(hard_cap, int) or isinstance(hard_cap, bool) or hard_cap <= 0:
        raise OmxError(f"hard_cap must be a positive int, got {hard_cap!r}.")

    def _crit() -> dict:
        state = load_state(paths)
        if state.get("active_loop"):
            raise OmxError(
                "a loop is already armed for this root "
                f"({state['active_loop'].get('run_id')!r}); run `omx loop-disarm` first.")
        # lease first (loud-fails on another session's young lease), then write.
        acquire_run_lease(paths, rid, session_id=session_id, now_iso=now_iso)
        try:
            # a re-arm must not read a prior 'done' marker (D-R4-8)
            marker = paths.loop_marker_json(rid)
            if marker.exists():
                marker.unlink()
            envelope = {
                "run_id": rid,
                "armed_at": now_iso,
                "deadline": compute_deadline(now_iso, max_runtime_s),
                "iteration": 0,
                "hard_cap": hard_cap,
                "adopted_session": None,
            }
            state["active_loop"] = envelope
            save_state(paths, state)
            return envelope
        except BaseException:
            release_run_lease(paths, rid)  # roll the lease back on a write failure
            raise

    from omx_core.lock import with_file_lock as _wfl  # explicit local alias
    return _wfl(paths.state_lock(), _crit)


def mark_loop_done(paths: OmxPaths, run_id, *, reason, summary, now_iso) -> dict:
    """Atomically write runs/<run_id>/loop-status.json — the loop-completion
    marker (R4 #7, D-R4-8). Overwrite is allowed: a re-run of a run id refreshes
    the marker (history lives in the ledger, not here). `now_iso` is the AWARE
    UTC instant the caller computes; `reason` is the disarm reason
    (done|deadline|cancel|error|hard_cap|plateau|fault_circuit)."""
    marker = {
        "schema_version": 1,
        "phase": "done",
        "reason": reason,
        "summary": summary,
        "ended_at": now_iso,
    }
    target = paths.loop_marker_json(run_id)
    with atomic_path(target) as tmp:
        tmp.write_text(json.dumps(marker, indent=2, sort_keys=True))
    return marker


def disarm_loop(paths: OmxPaths, *, reason="cancel", now_iso=None) -> dict:
    """Clear the armed loop (idempotent). The gate's standing exit (spec 2.4).
    Under the state mutex: writes the completion marker for the armed run,
    releases the lease UNCONDITIONALLY (whichever process disarms is
    authoritatively ending the loop — critic C2, this is what lets a gate
    self-disarm clean up), then nulls active_loop. `now_iso` defaults to an
    aware-UTC instant computed here (the handler path passes none)."""
    from datetime import datetime, timezone
    from omx_core.lock import release_run_lease, with_file_lock
    from omx_core.state import load_state, save_state
    ended_at = now_iso or datetime.now(timezone.utc).isoformat()

    def _crit() -> dict:
        state = load_state(paths)
        env = state.get("active_loop")
        if env is None:
            return {"was_armed": False, "iteration": None, "reason": reason}
        rid = env.get("run_id")
        if rid:
            mark_loop_done(paths, rid, reason=reason,
                           summary=f"iteration {env.get('iteration')}", now_iso=ended_at)
            release_run_lease(paths, rid)  # unconditional
        state["active_loop"] = None
        save_state(paths, state)
        return {"was_armed": True, "iteration": env.get("iteration"), "reason": reason}

    return with_file_lock(paths.state_lock(), _crit)
