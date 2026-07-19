import json

from omx_core.omx_paths import OmxPaths
from omx_core.state import DEFAULT_STATE, load_state, save_state


def test_load_missing_returns_default_copy(tmp_path):
    p = OmxPaths(tmp_path)
    st = load_state(p)
    assert st == DEFAULT_STATE
    # must be a copy, not the module-level dict (mutating it must not poison defaults)
    st["active_loop"] = "x"
    assert DEFAULT_STATE["active_loop"] is None


def test_save_then_load_roundtrip(tmp_path):
    p = OmxPaths(tmp_path)
    st = load_state(p)
    st["current_phase"] = "analyze"
    st["session_id"] = "20260530-101010-42"
    save_state(p, st)
    again = load_state(p)
    assert again["current_phase"] == "analyze"
    assert again["session_id"] == "20260530-101010-42"
    assert again["omx_state_version"] == 1


def test_save_is_atomic_no_tmp_left(tmp_path):
    p = OmxPaths(tmp_path)
    save_state(p, load_state(p))
    cache_dir = p.state_json().parent
    leftovers = [x.name for x in cache_dir.iterdir() if x.name.endswith(".tmp")]
    assert leftovers == []


def test_save_writes_valid_json(tmp_path):
    p = OmxPaths(tmp_path)
    save_state(p, load_state(p))
    data = json.loads(p.state_json().read_text())
    assert data["omx_state_version"] == 1
