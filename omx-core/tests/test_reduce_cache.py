import numpy as np
from omx_core.omx_paths import OmxPaths
from omx_core.reduce.cache import read_cache, write_cache


def test_read_missing_returns_none(tmp_path):
    p = OmxPaths(tmp_path)
    assert read_cache(p, "run01", source="eval_summary", metric="ss_error") is None


def test_write_then_read_roundtrip(tmp_path):
    p = OmxPaths(tmp_path)
    arrays = {"x": np.arange(5), "y": np.ones((3, 2))}
    out = write_cache(p, "run01", source="eval_summary", metric="ss_error", arrays=arrays)
    assert out.suffix == ".npz"
    back = read_cache(p, "run01", source="eval_summary", metric="ss_error")
    assert set(back) == {"x", "y"}
    assert np.array_equal(back["x"], np.arange(5))
    assert back["y"].shape == (3, 2)


def test_write_is_atomic_no_tmp_left(tmp_path):
    p = OmxPaths(tmp_path)
    write_cache(p, "run01", source="eval_summary", metric="ss_error", arrays={"x": np.arange(3)})
    cache_dir = p.cache_path("run01", source="eval_summary", metric="ss_error").parent
    leftovers = [f.name for f in cache_dir.iterdir() if f.name.endswith(".tmp")]
    assert leftovers == []
