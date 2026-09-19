"""Tests for the completion-gate memory (design doc §5): a receipt recording
a computed verdict, and a defer recording a human's decision to close anyway.
Both cross the ssh boundary a later task wires up -- these tests only cover
the storage layer. Fixture trees under tmp_path; no network, no ssh."""
from datetime import timedelta

from omx_core.clock import now_iso, parse_iso_utc
from omx_core.completion import (
    active_defer,
    read_receipt,
    receipt_satisfies,
    write_defer,
    write_receipt,
)
from omx_core.omx_paths import OmxError, OmxPaths

CHECKED_VERDICT = {"state": "checked", "runs": ["runs/alpha", "runs/beta"]}
INCOMPLETE_VERDICT = {"state": "incomplete", "runs": ["runs/alpha"]}


def _shift(instant_iso: str, **delta) -> str:
    return (parse_iso_utc(instant_iso, "instant") + timedelta(**delta)).isoformat()


def test_write_and_read_receipt_roundtrip(tmp_path):
    paths = OmxPaths(root=tmp_path)
    t0 = now_iso()
    write_receipt(paths, CHECKED_VERDICT, source="local", now_iso=t0)
    receipt = read_receipt(paths)
    assert receipt["checked_at"] == t0
    assert receipt["root"] == str(tmp_path)
    assert receipt["state"] == "checked"
    assert receipt["runs_checked"] == 2
    assert receipt["source"] == "local"
    assert isinstance(receipt["omx_version"], str) and receipt["omx_version"]


def test_receipt_lands_under_hq_runtime_when_anchored(tmp_path):
    anchor = tmp_path / ".hq" / ".anchor"
    anchor.parent.mkdir(parents=True)
    anchor.write_text("id: test-anchor\n", encoding="utf-8")
    paths = OmxPaths(root=tmp_path)
    write_receipt(paths, CHECKED_VERDICT, source="remote", now_iso=now_iso())
    assert (tmp_path / ".hq" / "runtime" / "experiments" / "completion-receipt.json").is_file()
    assert not (tmp_path / ".omx").exists()


def test_missing_receipt_returns_none(tmp_path):
    paths = OmxPaths(root=tmp_path)
    assert read_receipt(paths) is None


def test_corrupt_receipt_file_returns_none_without_raising(tmp_path):
    paths = OmxPaths(root=tmp_path)
    target = tmp_path / ".omx" / "completion-receipt.json"
    target.parent.mkdir(parents=True)
    target.write_text("{not valid json", encoding="utf-8")
    assert read_receipt(paths) is None


def test_fresh_checked_receipt_satisfies():
    t0 = now_iso()
    receipt = {"checked_at": t0, "state": "checked"}
    assert receipt_satisfies(receipt, t0, max_age_h=12) is True


def test_checked_receipt_aged_past_max_age_does_not_satisfy():
    t0 = now_iso()
    receipt = {"checked_at": t0, "state": "checked"}
    later = _shift(t0, hours=13)
    assert receipt_satisfies(receipt, later, max_age_h=12) is False


def test_incomplete_receipt_never_satisfies_at_any_age():
    t0 = now_iso()
    receipt = {"checked_at": t0, "state": "incomplete"}
    assert receipt_satisfies(receipt, t0, max_age_h=10_000) is False


def test_unparseable_checked_at_does_not_satisfy_and_does_not_raise():
    receipt = {"checked_at": "not-a-timestamp", "state": "checked"}
    assert receipt_satisfies(receipt, now_iso(), max_age_h=12) is False


def test_receipt_from_the_future_beyond_clock_skew_does_not_satisfy():
    t0 = now_iso()
    future = _shift(t0, minutes=5)
    receipt = {"checked_at": future, "state": "checked"}
    assert receipt_satisfies(receipt, t0, max_age_h=12) is False


def test_write_defer_then_active_defer_true(tmp_path):
    paths = OmxPaths(root=tmp_path)
    t0 = now_iso()
    write_defer(paths, "waiting on hardware, closing anyway", t0)
    assert active_defer(paths, t0, ttl_h=12) is True


def test_defer_expires_after_ttl(tmp_path):
    paths = OmxPaths(root=tmp_path)
    t0 = now_iso()
    write_defer(paths, "waiting on hardware, closing anyway", t0)
    later = _shift(t0, hours=13)
    assert active_defer(paths, later, ttl_h=12) is False


def test_no_defer_file_means_not_active(tmp_path):
    paths = OmxPaths(root=tmp_path)
    assert active_defer(paths, now_iso(), ttl_h=12) is False


def test_empty_reason_defer_refused(tmp_path):
    paths = OmxPaths(root=tmp_path)
    try:
        write_defer(paths, "   ", now_iso())
        assert False, "expected OmxError"
    except OmxError:
        pass
    assert active_defer(paths, now_iso(), ttl_h=12) is False


def test_receipt_and_defer_are_independent_files(tmp_path):
    """A defer must survive a new receipt being written (decision 4) -- they
    are two separate files, not one record."""
    paths = OmxPaths(root=tmp_path)
    t0 = now_iso()
    write_defer(paths, "waiting on hardware, closing anyway", t0)
    write_receipt(paths, INCOMPLETE_VERDICT, source="local", now_iso=t0)
    assert active_defer(paths, t0, ttl_h=12) is True
    receipt = read_receipt(paths)
    assert receipt["state"] == "incomplete"
