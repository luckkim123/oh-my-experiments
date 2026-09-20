"""Tests for omx_core.profile.validate_run_completion / load_run_completion
(design doc §3, D2) — the run_completion contract's parse + validate layer."""
import pytest
import yaml
from omx_core.omx_paths import OmxError, OmxPaths
from omx_core.profile import (
    bootstrap_profile,
    default_metrics,
    load_run_completion,
    validate_run_completion,
)


def _good_block():
    return {
        "runs": "runs/*",
        "finished": "checkpoints/*.pt",
        "exclude": ["runs/smoke-*"],
        "required": ["eval/*.json", "plots/*.png"],
        "how": "python analysis/eval.py static --run {run}",
    }


def _bootstrap_with(tmp_path, run_completion=None):
    paths = OmxPaths(root=tmp_path)
    metrics = default_metrics()
    if run_completion is not None:
        metrics["run_completion"] = run_completion
    bootstrap_profile(paths, profile_name="isaaclab", metrics=metrics)
    return paths


def test_valid_block_round_trips_unchanged():
    block = _good_block()
    assert validate_run_completion(block) == _good_block()


def test_block_without_exclude_is_valid():
    d = _good_block()
    del d["exclude"]
    assert validate_run_completion(d) == d


def test_non_mapping_raises():
    with pytest.raises(OmxError):
        validate_run_completion(["not", "a", "mapping"])


@pytest.mark.parametrize("key", ["runs", "finished", "required", "how"])
def test_missing_key_raises(key):
    d = _good_block()
    del d[key]
    # match=key alone is inert for key="required": "missing required key" always
    # contains the substring "required" regardless of which key is actually missing.
    # Pin the quotes so the assertion checks the NAMED key, not template boilerplate.
    with pytest.raises(OmxError, match=rf"'{key}'"):
        validate_run_completion(d)


@pytest.mark.parametrize("key", ["runs", "finished", "how"])
def test_empty_string_field_raises(key):
    d = _good_block()
    d[key] = ""
    with pytest.raises(OmxError, match=key):
        validate_run_completion(d)


@pytest.mark.parametrize("key", ["runs", "finished", "how"])
def test_non_string_field_raises(key):
    d = _good_block()
    d[key] = 123
    with pytest.raises(OmxError, match=key):
        validate_run_completion(d)


def test_required_not_a_list_raises():
    d = _good_block()
    d["required"] = "eval/*.json"
    with pytest.raises(OmxError, match="required"):
        validate_run_completion(d)


def test_required_empty_list_raises():
    d = _good_block()
    d["required"] = []
    with pytest.raises(OmxError, match="required"):
        validate_run_completion(d)


def test_required_with_empty_string_item_raises():
    d = _good_block()
    d["required"] = ["eval/*.json", ""]
    with pytest.raises(OmxError, match="required"):
        validate_run_completion(d)


def test_required_with_non_string_item_raises():
    d = _good_block()
    d["required"] = ["eval/*.json", 7]
    with pytest.raises(OmxError, match="required"):
        validate_run_completion(d)


def test_exclude_not_a_list_raises():
    d = _good_block()
    d["exclude"] = "runs/smoke-*"
    with pytest.raises(OmxError, match="exclude"):
        validate_run_completion(d)


def test_exclude_with_non_string_item_raises():
    d = _good_block()
    d["exclude"] = [123]
    with pytest.raises(OmxError, match="exclude"):
        validate_run_completion(d)


@pytest.mark.parametrize("key", ["runs", "finished"])
def test_absolute_glob_rejected(key):
    d = _good_block()
    d[key] = "/abs/path/*"
    with pytest.raises(OmxError, match=key):
        validate_run_completion(d)


@pytest.mark.parametrize("key", ["runs", "finished"])
def test_dotdot_glob_rejected(key):
    d = _good_block()
    d[key] = "../escape/*"
    with pytest.raises(OmxError, match=key):
        validate_run_completion(d)


def test_absolute_required_glob_rejected():
    d = _good_block()
    d["required"] = ["/abs/eval.json"]
    with pytest.raises(OmxError, match="required"):
        validate_run_completion(d)


def test_dotdot_required_glob_rejected():
    d = _good_block()
    d["required"] = ["../escape/eval.json"]
    with pytest.raises(OmxError, match="required"):
        validate_run_completion(d)


def test_absolute_exclude_glob_rejected():
    d = _good_block()
    d["exclude"] = ["/abs/runs/smoke-*"]
    with pytest.raises(OmxError, match="exclude"):
        validate_run_completion(d)


def test_dotdot_exclude_glob_rejected():
    d = _good_block()
    d["exclude"] = ["../escape/*"]
    with pytest.raises(OmxError, match="exclude"):
        validate_run_completion(d)


def test_dotdot_embedded_mid_path_rejected():
    # "runs/../escape/*" contains a '..' segment even though it doesn't start with it
    d = _good_block()
    d["runs"] = "runs/../escape/*"
    with pytest.raises(OmxError, match="runs"):
        validate_run_completion(d)


def test_load_absent_returns_none(tmp_path):
    _bootstrap_with(tmp_path)
    assert load_run_completion(tmp_path) is None


def test_load_present_returns_validated_block(tmp_path):
    paths = _bootstrap_with(tmp_path, run_completion=_good_block())
    result = load_run_completion(paths)
    assert result == _good_block()


def test_load_present_invalid_raises(tmp_path):
    paths = _bootstrap_with(tmp_path)
    metrics_path = paths.profile_file("metrics.yaml")
    data = yaml.safe_load(metrics_path.read_text())
    data["run_completion"] = {"runs": "runs/*"}  # missing finished/required/how
    metrics_path.write_text(yaml.safe_dump(data, sort_keys=True))
    with pytest.raises(OmxError):
        load_run_completion(tmp_path)


def test_load_accepts_omxpaths_or_plain_root(tmp_path):
    paths = _bootstrap_with(tmp_path, run_completion=_good_block())
    # Assert against the expected block, not just cross-equality -- two None
    # results would satisfy a bare `load_run_completion(a) == load_run_completion(b)`.
    expected = _good_block()
    assert load_run_completion(tmp_path) == expected
    assert load_run_completion(paths) == expected
