"""Tests for omx_core.coverage — report vocabulary/engine completeness lint.

GAP 4 from the dr-harder reporting incident: an exp-analyze report can cover only
a slice of the profile vocabulary (eval-side) and skip the training-dynamics
diagnostic groups AND the profile's training-log diagnostic engine, and still
"pass". The teacher report referenced ~29/51 vocab tokens but cited ZERO engine
DIAGNOSIS output — a count-only lint would wave it through. So coverage checks BOTH
(a) every declared diagnostic group has >=1 referenced metric, and (b) >=1 engine
marker is cited (the report was grounded in the engine, not hand-extracted scalars).
"""
import pytest

from omx_core.coverage import CoverageResult, check_coverage
from omx_core.omx_paths import OmxError


# --- a minimal profile dict shaped like metrics.yaml's optional lint fields ---
def _profile(groups=None, markers=None):
    p = {
        "metrics": ["reward_total", "Reward/att_rp", "entropy", "Loss/cost_value",
                    "Encoder/z_std", "Constraint/margin/attitude", "doraemon_success_rate"],
        "output_root": "experiments",
    }
    if groups is not None:
        p["groups"] = groups
    if markers is not None:
        p["engine_markers"] = markers
    return p


_GROUPS = {
    "reward_decomp": ["Reward/att_rp", "Reward/lin_vel"],
    "trpo": ["entropy", "line_search_success"],
    "critic": ["Loss/value_function", "Loss/cost_value"],
    "encoder": ["Encoder/z_std", "Policy/encoder_grad_norm"],
    "constraint": ["Constraint/margin/attitude"],
    "doraemon": ["doraemon_success_rate", "DORAEMON/ess_ratio"],
}
_MARKERS = ["DIAGNOSIS", "changepoint", "plateau", "TREND"]


def test_no_groups_field_is_a_noop_pass():
    # a profile without the optional groups field cannot fail coverage (back-compat)
    res = check_coverage("anything at all", _profile())
    assert isinstance(res, CoverageResult)
    assert res.ok is True
    assert res.missing_groups == []
    assert res.engine_cited is True  # nothing to require -> vacuously satisfied


def test_full_coverage_passes():
    report = (
        "Reward/att_rp dominates; lin_vel small. entropy alive, line_search_success 1.0. "
        "Loss/value_function and cost_value converged. Encoder/z_std healthy, "
        "encoder_grad_norm live. Constraint margin/attitude satisfied. "
        "doraemon_success_rate 0.96, ess_ratio 0.87. "
        "Engine [DIAGNOSIS]: reward plateau since 10%, changepoint iter 434."
    )
    res = check_coverage(report, _profile(groups=_GROUPS, markers=_MARKERS))
    assert res.ok is True
    assert res.missing_groups == []
    assert res.engine_cited is True


def test_engine_skip_is_caught_even_when_groups_covered():
    # THE incident: all vocab groups touched via hand-extracted final scalars, but
    # the engine ([DIAGNOSIS]/changepoint/plateau/TREND) was never run -> must FAIL.
    report = (
        "Reward/att_rp dominates; lin_vel small. entropy alive, line_search_success 1.0. "
        "Loss/value_function and cost_value converged. Encoder/z_std healthy, "
        "encoder_grad_norm live. Constraint margin/attitude satisfied. "
        "doraemon_success_rate 0.96, ess_ratio 0.87."
        # NOTE: no engine marker anywhere -> hand-extracted final scalars only
    )
    res = check_coverage(report, _profile(groups=_GROUPS, markers=_MARKERS))
    assert res.ok is False
    assert res.engine_cited is False
    assert res.missing_groups == []  # groups ARE covered; the failure is engine-skip


def test_missing_group_is_reported():
    # a report that skips the whole 'doraemon' and 'encoder' groups
    report = (
        "Reward/att_rp dominates. entropy alive. cost_value converged. "
        "Constraint margin/attitude satisfied. [DIAGNOSIS] plateau."
    )
    res = check_coverage(report, _profile(groups=_GROUPS, markers=_MARKERS))
    assert res.ok is False
    assert set(res.missing_groups) == {"encoder", "doraemon"}


def test_missing_groups_and_engine_both_reported():
    report = "Reward/att_rp dominates. entropy alive. cost_value converged."
    res = check_coverage(report, _profile(groups=_GROUPS, markers=_MARKERS))
    assert res.ok is False
    assert "encoder" in res.missing_groups
    assert "doraemon" in res.missing_groups
    assert "constraint" in res.missing_groups
    assert res.engine_cited is False


def test_one_metric_per_group_is_enough():
    # a group passes if ANY one of its metrics is referenced (not all)
    report = (
        "Reward/att_rp ok. entropy ok. cost_value ok. Encoder/z_std ok. "
        "margin/attitude ok. doraemon_success_rate ok. [DIAGNOSIS] fine."
    )
    res = check_coverage(report, _profile(groups=_GROUPS, markers=_MARKERS))
    assert res.ok is True
    assert res.missing_groups == []


def test_leaf_token_match_ignores_path_prefix():
    # a slash-prefixed profile token ('Loss/cost_value', 'DORAEMON/ess_ratio',
    # 'Encoder/z_std') should match its bare leaf in prose ('cost_value', etc.)
    report = (
        "att_rp ok. entropy ok. cost_value converged. z_std ok. "
        "margin/attitude ok. ess_ratio 0.87. [DIAGNOSIS] plateau."
    )
    res = check_coverage(report, _profile(groups=_GROUPS, markers=_MARKERS))
    assert res.missing_groups == []
    assert res.ok is True


def test_markers_declared_but_none_cited_fails_with_groups_ok():
    report = (
        "Reward/att_rp. entropy. cost_value. Encoder/z_std. margin/attitude. "
        "doraemon_success_rate."
    )
    res = check_coverage(report, _profile(groups=_GROUPS, markers=_MARKERS))
    assert res.engine_cited is False
    assert res.ok is False


def test_no_markers_field_means_engine_not_required():
    # groups present but no engine_markers declared -> engine citation not required
    report = (
        "Reward/att_rp. entropy. cost_value. Encoder/z_std. margin/attitude. "
        "doraemon_success_rate."
    )
    res = check_coverage(report, _profile(groups=_GROUPS, markers=None))
    assert res.engine_cited is True  # vacuously
    assert res.ok is True


def test_groups_must_be_a_mapping_of_lists():
    with pytest.raises(OmxError):
        check_coverage("x", {"metrics": ["a"], "output_root": "e", "groups": ["not", "a", "map"]})


def test_empty_group_list_loud_fails():
    with pytest.raises(OmxError):
        check_coverage("x", {"metrics": ["a"], "output_root": "e", "groups": {"g": []}})
