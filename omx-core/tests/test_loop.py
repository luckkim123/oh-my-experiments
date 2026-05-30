"""Tests for omx_core.loop — deadline ceiling + pending-launch queue (Claude-free)."""
import json

import pytest

from omx_core.loop import compute_deadline, deadline_passed
from omx_core.omx_paths import OmxError


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
