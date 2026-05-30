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
