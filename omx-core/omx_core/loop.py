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
from datetime import datetime, timedelta

from omx_core.omx_paths import OmxError


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
    decide whether to stop the autonomous analyze/design/eval phase.
    """
    deadline = _parse_iso(deadline_iso, "deadline_iso")
    now = _parse_iso(now_iso, "now_iso")
    return now >= deadline
