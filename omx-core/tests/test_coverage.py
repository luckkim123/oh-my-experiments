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


# --- min_coverage strict mode (GAP 4b: ">=1 token" is too weak; a 4/7-groups-with-
#     one-token-each report passes the lenient gate. strict mode requires a FRACTION
#     of each group's tokens to be referenced, catching shallow partial coverage.) ---

def test_group_hits_reported_per_group():
    # CoverageResult must expose per-group hit/total so the agent sees WHERE it is thin
    report = "Reward/att_rp and lin_vel. entropy. cost_value. z_std. margin/attitude. doraemon_success_rate. [DIAGNOSIS]"
    res = check_coverage(report, _profile(groups=_GROUPS, markers=_MARKERS))
    assert res.group_hits["reward_decomp"] == (2, 2)  # both tokens referenced
    assert res.group_hits["critic"] == (1, 2)         # only cost_value, not value_function
    assert res.group_hits["constraint"] == (1, 1)     # single-token group fully hit


def test_min_coverage_none_is_lenient_default():
    # default (min_coverage=None) keeps the back-compat ">=1 token per group" behaviour
    report = (
        "Reward/att_rp ok. entropy ok. cost_value ok. Encoder/z_std ok. "
        "margin/attitude ok. doraemon_success_rate ok. [DIAGNOSIS] fine."
    )
    res = check_coverage(report, _profile(groups=_GROUPS, markers=_MARKERS))
    assert res.ok is True  # one token per group is enough when not strict


def test_strict_mode_fails_shallow_partial_coverage():
    # THE 3rd incident: a report that names only one token in groups that have several.
    # reward_decomp(7), trpo(7), critic(2), encoder(5) each get ONE token -> below 0.5.
    report = (
        "Reward/att_rp only. entropy only. cost_value only. Encoder/z_std only. "
        "margin/attitude. doraemon_success_rate. [DIAGNOSIS] plateau."
    )
    res = check_coverage(report, _profile(groups=_GROUPS, markers=_MARKERS), min_coverage=0.5)
    assert res.ok is False
    # groups whose hit-fraction is below 0.5 are flagged as thin
    assert "reward_decomp" in res.missing_groups
    assert "trpo" in res.missing_groups
    assert "encoder" in res.missing_groups
    # single-token groups that ARE hit stay satisfied (1/1 >= any frac)
    assert "constraint" not in res.missing_groups


def test_strict_mode_passes_full_coverage():
    report = (
        "Reward/att_rp, lin_vel, yaw_vel, bias, smoothness, thruster, torque all logged. "
        "entropy, noise_std, line_search_success, kl, surrogate_loss, actor_step, sigma_step. "
        "Loss/value_function and cost_value. Encoder/z_std, z_min, z_max, encoder_grad_norm, enc_step. "
        "barrier_penalty, margin/attitude, margin/cumul_yaw, margin/yaw_rate, margin/thruster_util, "
        "viol/attitude, viol/cumul_yaw, viol/yaw_rate, viol/thruster_util. "
        "doraemon_success_rate, entropy_before, kl_step, ess_ratio. "
        "ss_error roll pitch vx vy vz yaw. [DIAGNOSIS] [TREND] changepoint plateau."
    )
    res = check_coverage(report, _profile(groups=_GROUPS, markers=_MARKERS), min_coverage=0.5)
    assert res.ok is True
    assert res.missing_groups == []


def test_strict_mode_single_token_group_needs_only_one():
    # a group with a single token can never be asked for >1; 1/1 satisfies any frac
    report = "margin/attitude present. [DIAGNOSIS]"
    res = check_coverage(report, _profile(groups={"constraint": ["Constraint/margin/attitude"]},
                                          markers=_MARKERS), min_coverage=1.0)
    assert res.ok is True
    assert res.missing_groups == []


def test_min_coverage_out_of_range_loud_fails():
    with pytest.raises(OmxError):
        check_coverage("x", _profile(groups=_GROUPS), min_coverage=1.5)
    with pytest.raises(OmxError):
        check_coverage("x", _profile(groups=_GROUPS), min_coverage=0.0)
