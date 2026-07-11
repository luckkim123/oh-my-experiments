"""D-R5-5: one aware-UTC clock helper ends the naive-cli / aware-evaluator
_now_iso split. now_iso() is aware; now_iso_naive() is the same instant in the
wiki's naive format; parse_iso_utc() is a normalizing loud-fail parse (a naive
value gets UTC attached — exact, because every legacy writer was a UTC instant)."""
from datetime import datetime, timezone

import pytest

from omx_core import clock
from omx_core.omx_paths import OmxError


def test_now_iso_is_aware_utc():
    s = clock.now_iso()
    dt = datetime.fromisoformat(s)
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timezone.utc.utcoffset(None)
    assert s.endswith("+00:00")


def test_now_iso_naive_has_no_offset():
    s = clock.now_iso_naive()
    assert "+" not in s and not s.endswith("Z")
    assert datetime.fromisoformat(s).tzinfo is None


def test_now_iso_and_naive_are_the_same_instant():
    # both read the same wall clock; the only difference is the tz suffix.
    aware = datetime.fromisoformat(clock.now_iso())
    naive = datetime.fromisoformat(clock.now_iso_naive())
    # within a second of each other (two now() reads), naive == aware minus tz
    assert abs((aware.replace(tzinfo=None) - naive).total_seconds()) < 2


def test_parse_iso_utc_normalizes_naive_to_aware():
    dt = clock.parse_iso_utc("2026-07-11T10:00:00", "armed_at")
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_parse_iso_utc_keeps_aware():
    dt = clock.parse_iso_utc("2026-07-11T10:00:00+00:00", "now")
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_parse_iso_utc_naive_and_aware_same_instant_compare():
    # the whole point: a naive on-disk value and an aware now must subtract.
    naive = clock.parse_iso_utc("2026-07-11T10:00:00", "armed_at")
    aware = clock.parse_iso_utc("2026-07-11T12:00:00+00:00", "now")
    assert (aware - naive).total_seconds() == 7200.0


def test_parse_iso_utc_loud_fails_with_label():
    with pytest.raises(OmxError) as ei:
        clock.parse_iso_utc("not-a-timestamp", "deadline")
    assert "deadline" in str(ei.value)


def test_parse_iso_utc_loud_fails_on_non_string():
    with pytest.raises(OmxError):
        clock.parse_iso_utc(None, "now")


def test_lease_ages_pre_r5_naive_armed_at_via_real_subtraction(tmp_path):
    # a pre-R5 lease with a NAIVE armed_at must age via real subtraction against
    # the new aware now (the normalizer), NOT the mtime fallback. A 10h-old naive
    # lease is stale (> 2h default) and gets reaped, regardless of file mtime.
    import json
    from omx_core.lock import acquire_run_lease, read_run_lease
    from omx_core.omx_paths import OmxPaths
    p = OmxPaths(root=str(tmp_path))
    lock = p.loop_lock("run1")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"session_id": "old", "armed_at": "2026-07-11T00:00:00",
                                "armed_by_pid": 1}))  # NAIVE armed_at, pre-R5 shape
    lease = acquire_run_lease(p, "run1", session_id="new",
                              now_iso="2026-07-11T10:00:00+00:00")  # aware, +10h
    assert lease["session_id"] == "new"                 # reaped via real subtraction
    assert read_run_lease(p, "run1")["session_id"] == "new"


def test_pending_launch_naive_queued_at_reads_cleanly(tmp_path):
    # a naive queued_at in an existing pending-launch.json must read without error
    from omx_core.loop import queue_pending_launch, read_pending_launch
    from omx_core.omx_paths import OmxPaths
    p = OmxPaths(root=str(tmp_path))
    queue_pending_launch(p, "run1", proposal_id="20260711-100000-x",
                         launch_delta="d", gpu_gate="g",
                         queued_at="2026-07-11T10:00:00")  # naive — read-only field
    assert read_pending_launch(p, "run1")["queued_at"] == "2026-07-11T10:00:00"
