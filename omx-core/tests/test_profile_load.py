import pytest
from omx_core.omx_paths import OmxPaths, Profile, OmxError
from omx_core.profile import bootstrap_profile, load_profile, default_metrics


def _bootstrap(root):
    paths = OmxPaths(root=root)
    bootstrap_profile(paths, profile_name="isaaclab", metrics=default_metrics())
    return paths


def test_load_profile_builds_vocabulary_tier(tmp_path):
    _bootstrap(tmp_path)
    prof = load_profile(tmp_path)
    assert isinstance(prof, Profile)
    assert "ss_error" in prof.metrics
    assert "trajectory" in prof.views
    assert "by_axis" in prof.aggs
    assert "eval_summary" in prof.sources
    assert prof.run_id_regex is None


def test_loaded_profile_enforces_vocab_in_paths(tmp_path):
    _bootstrap(tmp_path)
    prof = load_profile(tmp_path)
    paths = OmxPaths(root=tmp_path, profile=prof)
    p = paths.analysis_plot("experiments", "run1", "20260530-101010-compare",
                            metric="ss_error", view="trajectory")
    assert p.name == "ss_error__trajectory.png"
    with pytest.raises(OmxError):
        paths.analysis_plot("experiments", "run1", "20260530-101010-compare",
                            metric="not_a_metric", view="trajectory")


def test_load_profile_missing_raises(tmp_path):
    with pytest.raises(OmxError):
        load_profile(tmp_path)  # no .omx/profile/metrics.yaml
