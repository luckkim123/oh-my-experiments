"""Tests for omx_core.profile — Claude-free profile bootstrap (build #3)."""
import pytest

from omx_core.omx_paths import OmxError
from omx_core.profile import validate_metrics_schema


def _good():
    return {
        "pending_approval": True,
        "output_root": "experiments",
        "metrics": ["ss_error", "attitude"],
        "views": ["trajectory"],
        "aggs": ["by_axis"],
        "sources": ["eval_summary"],
        "run_id_regex": None,
        "keep_policy": "pass_only",
        "score_formula": None,
    }


def test_valid_minimal_schema_passes():
    # returns the validated dict unchanged (echo-through, loud-fail otherwise)
    assert validate_metrics_schema(_good()) == _good()


def test_missing_output_root_raises():
    d = _good(); del d["output_root"]
    with pytest.raises(OmxError, match="output_root"):
        validate_metrics_schema(d)


def test_empty_metrics_list_raises():
    d = _good(); d["metrics"] = []
    with pytest.raises(OmxError, match="metrics"):
        validate_metrics_schema(d)


def test_metric_with_double_underscore_raises():
    # validate_token forbids '__' (it is the field separator in filenames)
    d = _good(); d["metrics"] = ["ss__error"]
    with pytest.raises(OmxError, match="metric"):
        validate_metrics_schema(d)


def test_uppercase_view_token_raises():
    d = _good(); d["views"] = ["Trajectory"]
    with pytest.raises(OmxError, match="view"):
        validate_metrics_schema(d)


def test_bad_keep_policy_raises():
    d = _good(); d["keep_policy"] = "always_keep"
    with pytest.raises(OmxError, match="keep_policy"):
        validate_metrics_schema(d)


def test_score_improvement_requires_formula():
    d = _good(); d["keep_policy"] = "score_improvement"; d["score_formula"] = None
    with pytest.raises(OmxError, match="score_formula"):
        validate_metrics_schema(d)


def test_score_improvement_with_formula_passes():
    d = _good(); d["keep_policy"] = "score_improvement"
    d["score_formula"] = "mean(ss_error) + 0.5 * cv(ss_error)"
    assert validate_metrics_schema(d)["score_formula"].startswith("mean")


def test_bad_run_id_regex_raises():
    d = _good(); d["run_id_regex"] = "([unclosed"
    with pytest.raises(OmxError, match="run_id_regex"):
        validate_metrics_schema(d)


def test_good_run_id_regex_passes():
    d = _good(); d["run_id_regex"] = r"\d{6}_.*"
    assert validate_metrics_schema(d)["run_id_regex"] == r"\d{6}_.*"


def test_pending_approval_must_be_true_when_bootstrapping():
    d = _good(); d["pending_approval"] = False
    with pytest.raises(OmxError, match="pending_approval"):
        validate_metrics_schema(d)


def test_score_formula_ignored_under_pass_only():
    # under pass_only, a present score_formula is allowed (not required, not rejected)
    d = _good(); d["score_formula"] = "anything"
    assert validate_metrics_schema(d) == d


import yaml

from omx_core.omx_paths import OmxPaths
from omx_core.profile import bootstrap_profile


def _bootstrap(tmp_path, **kw):
    paths = OmxPaths(root=tmp_path)
    metrics = kw.pop("metrics", _good())
    return paths, bootstrap_profile(paths, profile_name="isaaclab", metrics=metrics, **kw)


def test_bootstrap_writes_all_four_files(tmp_path):
    paths, written = _bootstrap(tmp_path)
    for name in ("evaluator.sh", "metrics.yaml", "rules.md", "launch.sh"):
        assert paths.profile_file(name).exists(), f"{name} not written"
    assert {p.name for p in written} == {"evaluator.sh", "metrics.yaml", "rules.md", "launch.sh", "tree.yaml"}


def test_bootstrap_metrics_yaml_roundtrips_and_is_valid(tmp_path):
    paths, _ = _bootstrap(tmp_path)
    loaded = yaml.safe_load(paths.profile_file("metrics.yaml").read_text())
    assert loaded["pending_approval"] is True
    assert loaded["metrics"] == _good()["metrics"]
    validate_metrics_schema(loaded)


def test_bootstrap_evaluator_copied_from_reference(tmp_path):
    paths, _ = _bootstrap(tmp_path)
    written = paths.profile_file("evaluator.sh").read_text()
    reference = paths.reference_evaluator("isaaclab").read_text()
    assert written == reference


def test_bootstrap_invalid_metrics_writes_nothing(tmp_path):
    bad = _good(); bad["keep_policy"] = "nope"
    paths = OmxPaths(root=tmp_path)
    with pytest.raises(OmxError, match="keep_policy"):
        bootstrap_profile(paths, profile_name="isaaclab", metrics=bad)
    assert not paths.profile_file("metrics.yaml").exists()
    assert not paths.profile_dir.exists() or list(paths.profile_dir.iterdir()) == []


def test_bootstrap_refuses_overwrite_without_force(tmp_path):
    paths, _ = _bootstrap(tmp_path)
    with pytest.raises(OmxError, match="already exists"):
        bootstrap_profile(paths, profile_name="isaaclab", metrics=_good(), force=False)


def test_bootstrap_force_overwrites(tmp_path):
    paths, _ = _bootstrap(tmp_path)
    m2 = _good(); m2["metrics"] = ["only_one"]
    bootstrap_profile(paths, profile_name="isaaclab", metrics=m2, force=True)
    loaded = yaml.safe_load(paths.profile_file("metrics.yaml").read_text())
    assert loaded["metrics"] == ["only_one"]


def test_bootstrap_unknown_reference_raises(tmp_path):
    paths = OmxPaths(root=tmp_path)
    with pytest.raises(OmxError):
        bootstrap_profile(paths, profile_name="nonexistent", metrics=_good())


def test_rules_and_launch_are_nonempty_templates(tmp_path):
    paths, _ = _bootstrap(tmp_path)
    assert "Analysis discipline" in paths.profile_file("rules.md").read_text()
    launch = paths.profile_file("launch.sh").read_text()
    assert launch.startswith("#!/usr/bin/env bash")
    assert "never auto-fired" in launch.lower() or "never runs it" in launch.lower()
