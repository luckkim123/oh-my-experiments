"""Tests for omx_core.loop — deadline ceiling + pending-launch queue (Claude-free)."""
import json

import pytest

from omx_core.loop import compute_deadline, deadline_passed, queue_pending_launch, read_pending_launch
from omx_core.omx_paths import OmxError, OmxPaths


def test_compute_deadline_adds_seconds():
    # 100 s after 2026-05-30T12:00:00+00:00 -> 12:01:40
    out = compute_deadline("2026-05-30T12:00:00+00:00", 100)
    assert out == "2026-05-30T12:01:40+00:00"


def test_compute_deadline_rejects_nonpositive():
    with pytest.raises(OmxError):
        compute_deadline("2026-05-30T12:00:00+00:00", 0)
    with pytest.raises(OmxError):
        compute_deadline("2026-05-30T12:00:00+00:00", -5)


def test_compute_deadline_rejects_bad_now():
    with pytest.raises(OmxError):
        compute_deadline("not-a-timestamp", 100)


def test_deadline_passed_true_when_now_after():
    assert deadline_passed("2026-05-30T12:00:00+00:00",
                           "2026-05-30T12:00:01+00:00") is True


def test_deadline_passed_false_when_now_before():
    assert deadline_passed("2026-05-30T12:00:00+00:00",
                           "2026-05-30T11:59:59+00:00") is False


def test_deadline_passed_true_at_exact_boundary():
    # at the deadline instant, the ceiling is reached (>=)
    assert deadline_passed("2026-05-30T12:00:00+00:00",
                           "2026-05-30T12:00:00+00:00") is True


def test_deadline_passed_rejects_bad_iso():
    with pytest.raises(OmxError):
        deadline_passed("2026-05-30T12:00:00+00:00", "garbage")


def test_queue_pending_launch_writes_artifact(tmp_path):
    p = OmxPaths(root=tmp_path)
    queue_pending_launch(
        p, "run-7",
        proposal_id="20260530-120000-next",
        launch_delta="set payload_cog_offset_xy_radius=0.05",
        gpu_gate="nvidia-smi shows GPU0 free",
        queued_at="2026-05-30T12:00:00+00:00",
    )
    target = p.pending_launch_json("run-7")
    assert target.exists()
    data = json.loads(target.read_text())
    assert data["status"] == "pending approval"
    assert data["proposal_id"] == "20260530-120000-next"
    assert data["launch_delta"] == "set payload_cog_offset_xy_radius=0.05"
    assert data["gpu_gate"] == "nvidia-smi shows GPU0 free"
    assert data["queued_at"] == "2026-05-30T12:00:00+00:00"


def test_queue_pending_launch_loud_fails_on_empty_proposal(tmp_path):
    p = OmxPaths(root=tmp_path)
    with pytest.raises(OmxError):
        queue_pending_launch(
            p, "run-7", proposal_id="  ", launch_delta="x",
            gpu_gate="g", queued_at="2026-05-30T12:00:00+00:00")


def test_queue_pending_launch_loud_fails_on_empty_delta(tmp_path):
    p = OmxPaths(root=tmp_path)
    with pytest.raises(OmxError):
        queue_pending_launch(
            p, "run-7", proposal_id="20260530-120000-next", launch_delta="",
            gpu_gate="g", queued_at="2026-05-30T12:00:00+00:00")


def test_read_pending_launch_roundtrips(tmp_path):
    p = OmxPaths(root=tmp_path)
    queue_pending_launch(
        p, "run-7", proposal_id="20260530-120000-next",
        launch_delta="x", gpu_gate="g", queued_at="2026-05-30T12:00:00+00:00")
    out = read_pending_launch(p, "run-7")
    assert out["proposal_id"] == "20260530-120000-next"
    assert out["status"] == "pending approval"


def test_read_pending_launch_returns_none_when_absent(tmp_path):
    p = OmxPaths(root=tmp_path)
    assert read_pending_launch(p, "run-7") is None


def test_read_pending_launch_loud_fails_on_corrupt_json(tmp_path):
    p = OmxPaths(root=tmp_path)
    target = p.pending_launch_json("run-7")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not json {")
    with pytest.raises(OmxError):
        read_pending_launch(p, "run-7")


def test_deadline_passed_loud_fails_on_naive_vs_aware():
    # one aware, one naive -> a clean OmxError, NOT a raw TypeError traceback
    with pytest.raises(OmxError):
        deadline_passed("2026-05-30T12:00:00", "2026-05-30T12:00:01+00:00")
    with pytest.raises(OmxError):
        deadline_passed("2026-05-30T12:00:00+00:00", "2026-05-30T12:00:01")


def test_deadline_passed_both_naive_still_works():
    # both naive is internally consistent -> a normal bool, no error
    assert deadline_passed("2026-05-30T12:00:00", "2026-05-30T12:00:01") is True
    assert deadline_passed("2026-05-30T12:00:00", "2026-05-30T11:59:59") is False
