"""Tests for omx_core.reduce.tb_final — named final-window scalars from TB series.

The dr-harder reporting incident (engine-output-unverified): the profile engine
reported "constraints=0" + no reward decomposition, the agent copied that as
truth, and wrote a false "reward 8-term decomposition unavailable" conclusion.
The raw TB held all 8 Reward/* tags. `tb-final` is the general, raw-TB-no-hand-read
home for pulling named final-window means for an arbitrary tag list, so a report
can cite "Reward/att_rp last-200-iter mean = 5.34" as a code-exec source instead
of eyeballing a curve or trusting an empty engine table.

The reduce fn is PURE: it takes the already-ingested series dict
(tag -> values, "_step/<tag>" -> steps), a tag list, and a window, and returns
{tag: mean-of-final-window}. TB file I/O stays in TensorboardAdapter.
"""
import numpy as np
import pytest

from omx_core.omx_paths import OmxError
from omx_core.reduce.tb_final import final_window_means


def _series(**tag_values):
    """Build a series dict like TensorboardAdapter.ingest returns: each tag gets
    a value array and a parallel _step/<tag> array (0..n-1)."""
    s = {}
    for tag, vals in tag_values.items():
        arr = np.asarray(vals, dtype=float)
        s[tag] = arr
        s[f"_step/{tag}"] = np.arange(len(arr), dtype=float)
    return s


def test_final_window_mean_of_last_n():
    # last 3 of [1,2,3,4,5,6] -> mean(4,5,6) = 5.0
    s = _series(**{"Reward/att_rp": [1, 2, 3, 4, 5, 6]})
    out = final_window_means(s, ["Reward/att_rp"], window=3)
    assert out == {"Reward/att_rp": 5.0}


def test_multiple_tags():
    s = _series(**{
        "Reward/att_rp": [10, 10, 10, 4, 5, 6],   # last 3 -> 5.0
        "Reward/total": [0, 0, 0, 7, 8, 9],        # last 3 -> 8.0
    })
    out = final_window_means(s, ["Reward/att_rp", "Reward/total"], window=3)
    assert out == {"Reward/att_rp": 5.0, "Reward/total": 8.0}


def test_window_larger_than_series_uses_all():
    # window 100 but only 4 samples -> mean of all 4
    s = _series(**{"Reward/bias": [2, 4, 6, 8]})
    out = final_window_means(s, ["Reward/bias"], window=100)
    assert out == {"Reward/bias": 5.0}


def test_window_default_is_200():
    # 250 samples, default window -> mean of last 200 (values 50..249)
    vals = list(range(250))
    s = _series(**{"Reward/lin_vel": vals})
    out = final_window_means(s, ["Reward/lin_vel"])  # no window arg
    expected = float(np.mean(vals[-200:]))
    assert out["Reward/lin_vel"] == pytest.approx(expected)


def test_missing_tag_loud_fails_listing_available():
    # a requested tag absent from the series is a loud error (cross-check should
    # have caught this; if a tag truly is absent, fail loudly, do not return 0)
    s = _series(**{"Reward/att_rp": [1, 2, 3]})
    with pytest.raises(OmxError) as ei:
        final_window_means(s, ["Reward/att_rp", "Reward/nope"], window=2)
    msg = str(ei.value)
    assert "Reward/nope" in msg
    assert "Reward/att_rp" in msg  # available tags are listed to aid the caller


def test_empty_tag_list_returns_empty_dict():
    s = _series(**{"Reward/att_rp": [1, 2, 3]})
    assert final_window_means(s, [], window=2) == {}


def test_empty_series_for_a_present_tag_loud_fails():
    # a tag present but with zero samples cannot yield a mean -> loud, not nan
    s = {"Reward/att_rp": np.array([], dtype=float),
         "_step/Reward/att_rp": np.array([], dtype=float)}
    with pytest.raises(OmxError):
        final_window_means(s, ["Reward/att_rp"], window=5)


def test_window_must_be_positive():
    s = _series(**{"Reward/att_rp": [1, 2, 3]})
    with pytest.raises(OmxError):
        final_window_means(s, ["Reward/att_rp"], window=0)
    with pytest.raises(OmxError):
        final_window_means(s, ["Reward/att_rp"], window=-5)


def test_step_keys_are_not_treated_as_tags():
    # passing a "_step/..." key as a tag is meaningless; it IS in the dict, but
    # the function must not silently average step indices. It's a real key, so it
    # would "work" numerically — guard by rejecting the _step/ prefix loudly.
    s = _series(**{"Reward/att_rp": [1, 2, 3]})
    with pytest.raises(OmxError):
        final_window_means(s, ["_step/Reward/att_rp"], window=2)
