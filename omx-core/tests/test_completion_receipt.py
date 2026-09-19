"""Tests for the completion-gate memory (design doc §5): a receipt recording
a computed verdict, and a defer recording a human's decision to close anyway.
Both cross the ssh boundary a later task wires up -- these tests only cover
the storage layer. Fixture trees under tmp_path; no network, no ssh."""
import os
from datetime import timedelta

import pytest
from omx_core.clock import now_iso, parse_iso_utc
from omx_core.completion import (
    active_defer,
    read_receipt,
    receipt_satisfies,
    write_defer,
    write_receipt,
)
from omx_core.omx_paths import OmxError, OmxPaths

_SKIP_UNLESS_POSIX_NONROOT = pytest.mark.skipif(
    os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="requires POSIX permission enforcement as a non-root user",
)

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


def test_corrupt_non_utf8_receipt_file_returns_none_without_raising(tmp_path):
    """UnicodeDecodeError is a ValueError, not an OSError -- a bare
    `except OSError` around read_text() lets it through uncaught (finding 1).
    A receipt that crossed an ssh boundary is exactly where a mangled-encoding
    payload would land."""
    paths = OmxPaths(root=tmp_path)
    target = tmp_path / ".omx" / "completion-receipt.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\xff\xfe\x00\x01not valid utf-8")
    with pytest.warns(RuntimeWarning):
        assert read_receipt(paths) is None


def test_corrupt_non_utf8_defer_file_returns_not_active_without_raising(tmp_path):
    """Same defect, reached through active_defer's shared _read_json path."""
    paths = OmxPaths(root=tmp_path)
    target = tmp_path / ".omx" / "completion-defer.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\xff\xfe\x00\x01not valid utf-8")
    with pytest.warns(RuntimeWarning):
        assert active_defer(paths, now_iso(), ttl_h=12) is False


@_SKIP_UNLESS_POSIX_NONROOT
def test_unreadable_existing_receipt_file_is_distinguished_from_missing(tmp_path):
    """finding 4: a PermissionError on a file that EXISTS must not read as
    silently as a genuinely absent one -- it still returns None (the contract
    never raises), but it is surfaced rather than swallowed identically."""
    paths = OmxPaths(root=tmp_path)
    target = tmp_path / ".omx" / "completion-receipt.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"state": "checked"}', encoding="utf-8")
    target.chmod(0o000)
    try:
        with pytest.warns(RuntimeWarning):
            assert read_receipt(paths) is None
    finally:
        target.chmod(0o644)


def test_write_receipt_uses_the_state_lock(tmp_path):
    """finding 3: atomic_path's fixed '.tmp' name needs a coarser lock around
    it (same discipline as ledger.py/loop.py) -- confirms the write actually
    goes through paths.state_lock() rather than just matching by coincidence."""
    paths = OmxPaths(root=tmp_path)
    write_receipt(paths, CHECKED_VERDICT, source="local", now_iso=now_iso())
    assert paths.state_lock().exists()


def test_fresh_checked_receipt_satisfies():
    t0 = now_iso()
    receipt = {"checked_at": t0, "state": "checked", "source": "remote"}
    assert receipt_satisfies(receipt, t0, max_age_h=12, expected_root="unused-for-remote") is True


def test_checked_receipt_aged_past_max_age_does_not_satisfy():
    t0 = now_iso()
    receipt = {"checked_at": t0, "state": "checked", "source": "remote"}
    later = _shift(t0, hours=13)
    assert receipt_satisfies(receipt, later, max_age_h=12, expected_root="unused-for-remote") is False


def test_incomplete_receipt_never_satisfies_at_any_age():
    t0 = now_iso()
    receipt = {"checked_at": t0, "state": "incomplete"}
    assert receipt_satisfies(receipt, t0, max_age_h=10_000, expected_root="unused") is False


def test_unparseable_checked_at_does_not_satisfy_and_does_not_raise():
    receipt = {"checked_at": "not-a-timestamp", "state": "checked", "source": "remote"}
    assert receipt_satisfies(receipt, now_iso(), max_age_h=12, expected_root="unused-for-remote") is False


def test_receipt_from_the_future_beyond_clock_skew_does_not_satisfy():
    t0 = now_iso()
    future = _shift(t0, minutes=5)
    receipt = {"checked_at": future, "state": "checked", "source": "remote"}
    assert receipt_satisfies(receipt, t0, max_age_h=12, expected_root="unused-for-remote") is False


def test_local_receipt_with_matching_root_satisfies(tmp_path):
    paths = OmxPaths(root=tmp_path)
    t0 = now_iso()
    write_receipt(paths, CHECKED_VERDICT, source="local", now_iso=t0)
    receipt = read_receipt(paths)
    assert receipt_satisfies(receipt, t0, max_age_h=12, expected_root=tmp_path) is True


def test_local_receipt_with_foreign_root_does_not_satisfy(tmp_path):
    """The review's reproduction: a receipt file copied in from a different
    project's store -- same content, wrong root."""
    t0 = now_iso()
    receipt = {"checked_at": t0, "root": "/some/other/project", "state": "checked",
               "runs_checked": 2, "omx_version": "0.5.0", "source": "local"}
    assert receipt_satisfies(receipt, t0, max_age_h=12, expected_root=tmp_path) is False


def test_remote_receipt_with_foreign_root_still_satisfies(tmp_path):
    """A remote receipt's root legitimately differs -- the far side of the ssh
    boundary design §5 crosses -- so root is not checked for source=="remote"."""
    t0 = now_iso()
    receipt = {"checked_at": t0, "root": "/container/output", "state": "checked",
               "runs_checked": 2, "omx_version": "0.5.0", "source": "remote"}
    assert receipt_satisfies(receipt, t0, max_age_h=12, expected_root=tmp_path) is True


def test_receipt_with_missing_source_does_not_satisfy(tmp_path):
    t0 = now_iso()
    receipt = {"checked_at": t0, "root": str(tmp_path), "state": "checked"}
    assert receipt_satisfies(receipt, t0, max_age_h=12, expected_root=tmp_path) is False


def test_receipt_with_unknown_source_does_not_satisfy(tmp_path):
    t0 = now_iso()
    receipt = {"checked_at": t0, "root": str(tmp_path), "state": "checked", "source": "bogus"}
    assert receipt_satisfies(receipt, t0, max_age_h=12, expected_root=tmp_path) is False


def _local_receipt(root, t0):
    return {"checked_at": t0, "root": str(root), "state": "checked",
            "runs_checked": 2, "omx_version": "0.5.0", "source": "local"}


def test_local_receipt_root_with_trailing_separator_still_satisfies(tmp_path):
    t0 = now_iso()
    receipt = _local_receipt(str(tmp_path) + os.sep, t0)
    assert receipt_satisfies(receipt, t0, max_age_h=12, expected_root=tmp_path) is True


def test_local_receipt_root_with_redundant_dot_segment_still_satisfies(tmp_path):
    t0 = now_iso()
    receipt = _local_receipt(f"{tmp_path}{os.sep}.{os.sep}", t0)
    assert receipt_satisfies(receipt, t0, max_age_h=12, expected_root=tmp_path) is True


def test_local_receipt_root_as_symlink_to_same_tree_still_satisfies(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    t0 = now_iso()
    receipt = _local_receipt(link, t0)
    assert receipt_satisfies(receipt, t0, max_age_h=12, expected_root=real) is True


def test_local_receipt_root_as_relative_path_to_same_tree_still_satisfies(tmp_path):
    t0 = now_iso()
    rel = os.path.relpath(tmp_path)
    receipt = _local_receipt(rel, t0)
    assert receipt_satisfies(receipt, t0, max_age_h=12, expected_root=tmp_path) is True


def test_local_receipt_root_a_number_does_not_satisfy_and_does_not_raise(tmp_path):
    """A hostile receipt's `root` field need not even be a string -- `Path()`
    raises TypeError on a non-path-like value where `!=` would not have."""
    t0 = now_iso()
    receipt = {"checked_at": t0, "root": 42, "state": "checked", "source": "local"}
    assert receipt_satisfies(receipt, t0, max_age_h=12, expected_root=tmp_path) is False


def test_local_receipt_root_absent_does_not_satisfy_and_does_not_raise(tmp_path):
    t0 = now_iso()
    receipt = {"checked_at": t0, "state": "checked", "source": "local"}
    assert receipt_satisfies(receipt, t0, max_age_h=12, expected_root=tmp_path) is False


def test_local_receipt_survives_its_tree_being_deleted(tmp_path):
    """A receipt legitimately outlives the tree it was written for -- Path.resolve()
    must not raise just because the path no longer exists (strict=False)."""
    gone = tmp_path / "will-be-deleted"
    gone.mkdir()
    t0 = now_iso()
    receipt = _local_receipt(gone, t0)
    gone.rmdir()
    assert receipt_satisfies(receipt, t0, max_age_h=12, expected_root=gone) is True


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
