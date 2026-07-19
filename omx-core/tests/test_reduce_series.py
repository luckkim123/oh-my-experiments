import numpy as np
import pytest
from omx_core.reduce.series import downsample, load_npz


def test_load_npz_returns_named_arrays(fixtures_dir):
    arrays = load_npz(fixtures_dir / "data_none.npz")
    assert "time" in arrays and "actual_roll_deg" in arrays
    assert arrays["actual_roll_deg"].shape == (100, 4)
    assert arrays["time"].shape == (100,)


def test_downsample_caps_point_count():
    arr = np.arange(10000)
    out = downsample(arr, max_points=1000)
    assert out.shape[0] <= 1000
    assert out[0] == 0                       # keeps the first point


def test_downsample_2d_thins_axis0_only():
    arr = np.arange(2000 * 4).reshape(2000, 4)
    out = downsample(arr, max_points=500)
    assert out.shape[0] <= 500
    assert out.shape[1] == 4                  # columns (envs) untouched


def test_downsample_noop_when_already_small():
    arr = np.arange(50)
    out = downsample(arr, max_points=1000)
    assert np.array_equal(out, arr)           # no change


def test_downsample_rejects_nonpositive_max():
    with pytest.raises(ValueError):
        downsample(np.arange(10), max_points=0)
