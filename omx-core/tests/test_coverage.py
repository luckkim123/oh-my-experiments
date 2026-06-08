"""Tests for omx_core.coverage — report vocabulary/engine completeness lint.

GAP 4 from the dr-harder reporting incident: an exp-analyze report can cover only
a slice of the profile vocabulary (eval-side) and skip the training-dynamics
diagnostic groups AND the profile's training-log diagnostic engine, and still
"pass". The teacher report referenced ~29/51 vocab tokens but cited ZERO engine
DIAGNOSIS output — a count-only lint would wave it through. So coverage checks BOTH
(a) every declared diagnostic group has >=1 referenced metric, and (b) >=1 engine
marker is cited (the report was grounded in the engine, not hand-extracted scalars).
"""
import json

import pytest

from omx_core.coverage import CoverageResult, CrossRefResult, check_coverage, check_cross_run_refs
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


# groups shaped like the real workspace metrics.yaml (several tokens each) so the
# strict-mode test reproduces the actual 3rd incident: a multi-token group named
# only once. (The lenient _GROUPS above are 2-token, where ceil(2*0.5)=1 still
# passes on one hit — that hides the very failure strict mode must catch.)
_STRICT_GROUPS = {
    "reward_decomp": ["Reward/att_rp", "Reward/lin_vel", "Reward/yaw_vel",
                      "Reward/bias", "Reward/smoothness", "Reward/thruster", "Reward/torque"],
    "trpo": ["entropy", "noise_std", "line_search_success", "kl",
             "Policy/surrogate_loss", "Grad/actor_step", "Grad/sigma_step"],
    "encoder": ["Encoder/z_std", "Encoder/z_min", "Encoder/z_max",
                "Policy/encoder_grad_norm", "Grad/enc_step"],
    "constraint": ["Constraint/margin/attitude"],  # single-token group
}


def test_strict_mode_fails_shallow_partial_coverage():
    # THE 3rd incident: a report that names only ONE token in groups that have several.
    # reward_decomp(7), trpo(7), encoder(5) each get one token -> below 0.5 -> thin.
    report = (
        "Reward/att_rp only. entropy only. Encoder/z_std only. "
        "margin/attitude present. [DIAGNOSIS] plateau."
    )
    res = check_coverage(report, _profile(groups=_STRICT_GROUPS, markers=_MARKERS), min_coverage=0.5)
    assert res.ok is False
    # groups whose hit-fraction is below 0.5 are flagged as thin
    assert "reward_decomp" in res.missing_groups  # 1/7 < ceil(7*0.5)=4
    assert "trpo" in res.missing_groups           # 1/7 < 4
    assert "encoder" in res.missing_groups        # 1/5 < ceil(5*0.5)=3
    # a single-token group that IS hit stays satisfied (1/1 >= max(1, ceil(1*0.5)))
    assert "constraint" not in res.missing_groups
    # group_hits exposes exactly where it is thin
    assert res.group_hits["reward_decomp"] == (1, 7)
    assert res.group_hits["constraint"] == (1, 1)


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
    res = check_coverage(report, _profile(groups=_STRICT_GROUPS, markers=_MARKERS), min_coverage=0.5)
    assert res.ok is True
    assert res.missing_groups == []
    assert res.group_hits["reward_decomp"] == (7, 7)  # full report names all tokens
    assert res.group_hits["encoder"] == (5, 5)


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


# --- GAP E: partial_groups surfacing in lenient default mode ---
# A report that passes lenient mode (>=1 token per group) but leaves some group
# tokens unreferenced should surface those groups in partial_groups, so the
# analyst cannot silently skip sub-group fields without any warning.

_MULTI_TOKEN_GROUPS = {
    "constraint": [
        "barrier_penalty",
        "Constraint/margin/attitude",
        "Constraint/margin/cumul_yaw",
        "Constraint/margin/yaw_rate",
        "Constraint/margin/thruster_util",
        "Constraint/viol/attitude",
        "Constraint/viol/cumul_yaw",
        "Constraint/viol/yaw_rate",
        "Constraint/viol/thruster_util",
    ],
    "reward_decomp": ["Reward/att_rp", "Reward/lin_vel", "Reward/yaw_vel"],
}


def test_partial_groups_populated_when_group_hit_lt_total():
    # lenient: ok=True (>=1 token per group), but partial_groups lists groups
    # where hits < total so the analyst sees which fields are missing.
    report = (
        # constraint: only barrier + margin/attitude referenced (2/9)
        "barrier_penalty present. margin/attitude ok. "
        # reward_decomp: all 3 tokens referenced
        "Reward/att_rp, lin_vel, yaw_vel all logged. "
        "[DIAGNOSIS] engine run."
    )
    res = check_coverage(report, _profile(groups=_MULTI_TOKEN_GROUPS, markers=_MARKERS))
    assert res.ok is True  # lenient mode: ok stays true (>=1 per group)
    assert res.missing_groups == []  # not a full missing group
    assert "constraint" in res.partial_groups  # 2/9 < 9 -> partial
    assert "reward_decomp" not in res.partial_groups  # 3/3 -> fully covered


def test_partial_groups_empty_when_all_fully_covered():
    report = (
        "barrier_penalty, margin/attitude, margin/cumul_yaw, margin/yaw_rate, "
        "margin/thruster_util, viol/attitude, viol/cumul_yaw, viol/yaw_rate, "
        "viol/thruster_util all referenced. "
        "Reward/att_rp, lin_vel, yaw_vel all logged. [DIAGNOSIS] fine."
    )
    res = check_coverage(report, _profile(groups=_MULTI_TOKEN_GROUPS, markers=_MARKERS))
    assert res.ok is True
    assert res.partial_groups == []


def test_partial_groups_empty_when_no_groups_declared():
    # a profile without groups -> partial_groups is empty (back-compat)
    res = check_coverage("anything", _profile())
    assert res.partial_groups == []


def test_partial_groups_not_overlap_with_missing_groups():
    # a group that is in missing_groups (0 hits) should NOT also be in partial_groups.
    # partial_groups = hits >= required (lenient: >=1) AND hits < total.
    # missing_groups = hits < required.
    report = (
        # reward_decomp: 1/3 referenced (att_rp only) -> lenient ok (>=1), partial (1<3)
        "Reward/att_rp only. "
        # constraint: 0 hits -> missing_groups, not partial
        "[DIAGNOSIS]."
    )
    res = check_coverage(report, _profile(groups=_MULTI_TOKEN_GROUPS, markers=_MARKERS))
    assert "constraint" in res.missing_groups
    assert "constraint" not in res.partial_groups  # missing -> not partial
    assert "reward_decomp" not in res.missing_groups
    assert "reward_decomp" in res.partial_groups  # 1/3 hits, lenient ok, partial


def test_partial_groups_single_token_group_never_partial():
    # a single-token group that is referenced is fully covered (hits == total == 1)
    groups = {"solo": ["only_metric"]}
    report = "only_metric present. [DIAGNOSIS]."
    res = check_coverage(report, _profile(groups=groups, markers=_MARKERS))
    assert res.ok is True
    assert res.partial_groups == []


def test_partial_groups_in_strict_mode_only_for_passing_thin_groups():
    # in strict mode, a group below threshold goes to missing_groups, not partial_groups.
    # partial_groups in strict mode = groups that meet strict threshold but are below total.
    # reward_decomp has 7 tokens. strict=0.5 requires ceil(7*0.5)=4.
    # referencing 4/7 -> passes strict, but 4 < 7 -> partial.
    report = (
        "Reward/att_rp, lin_vel, yaw_vel, bias logged. "  # 4/7 reward_decomp
        "entropy only. "                                   # 1/7 trpo -> fails strict
        "Encoder/z_std only. "                            # 1/5 encoder -> fails strict
        "margin/attitude ok. [DIAGNOSIS]."                 # constraint: 1/1 -> ok
    )
    res = check_coverage(report, _profile(groups=_STRICT_GROUPS, markers=_MARKERS),
                         min_coverage=0.5)
    # trpo (1/7 < 4) and encoder (1/5 < 3) fail strict -> missing_groups
    assert "trpo" in res.missing_groups
    assert "encoder" in res.missing_groups
    # reward_decomp (4/7 >= 4) passes strict but 4 < 7 -> partial
    assert "reward_decomp" in res.partial_groups
    # constraint (1/1) fully covered -> not partial
    assert "constraint" not in res.partial_groups


# =====================================================================
# required_sections — declared report sections (NOT metric tokens) must
# exist as headings. Catches a whole '## generalization' section being
# dropped, which the metric-token groups cannot see (the dr_harder
# 2026-06-08 incident: OOD/generalization section deleted, lint passed).
# =====================================================================
_SECTIONS = ["tracking", "generalization", "constraint", "doraemon", "verdict"]


def test_required_sections_absent_field_is_noop():
    # back-compat: a profile without required_sections cannot fail on it.
    # (no groups/markers either -> isolate the required_sections check)
    res = check_coverage("## tracking\nstuff", _profile())
    assert res.missing_sections == []
    assert res.ok is True


def test_required_sections_all_present_passes():
    report = (
        "## tracking error\nroll ss_error.\n"
        "## generalization (in-dist hard vs OOD)\nood gap.\n"
        "## constraint\nmargin/attitude.\n"
        "## doraemon\nsuccess_rate.\n"
        "## verdict\nbottom line.\n"
        "Reward/att_rp lin_vel entropy line_search_success Loss/value_function "
        "cost_value Encoder/z_std encoder_grad_norm margin/attitude "
        "doraemon_success_rate ess_ratio [DIAGNOSIS] changepoint"
    )
    p = _profile(groups=_GROUPS, markers=_MARKERS)
    p["required_sections"] = _SECTIONS
    res = check_coverage(report, p)
    assert res.missing_sections == []
    assert res.ok is True


def test_required_section_missing_fails():
    # generalization section dropped -> must be caught (the exact incident)
    report = (
        "## tracking error\nroll ss_error.\n"
        "## constraint\nmargin/attitude.\n"
        "## doraemon\nsuccess_rate.\n"
        "## verdict\nbottom line.\n"
        "Reward/att_rp lin_vel entropy line_search_success Loss/value_function "
        "cost_value Encoder/z_std encoder_grad_norm margin/attitude "
        "doraemon_success_rate ess_ratio [DIAGNOSIS] changepoint"
    )
    p = _profile(groups=_GROUPS, markers=_MARKERS)
    p["required_sections"] = _SECTIONS
    res = check_coverage(report, p)
    assert "generalization" in res.missing_sections
    assert res.ok is False  # a missing required section is a hard fail


def test_required_sections_match_is_substring_in_heading_only():
    # a section token must appear in a markdown HEADING line, not anywhere in prose.
    # Mentioning the word 'generalization' inside a paragraph must NOT satisfy it.
    report = (
        "## tracking error\nThe generalization to OOD is discussed below in prose only.\n"
        "## constraint\nx\n## doraemon\nx\n## verdict\nx\n"
        "Reward/att_rp lin_vel entropy line_search_success Loss/value_function "
        "cost_value Encoder/z_std encoder_grad_norm margin/attitude "
        "doraemon_success_rate ess_ratio [DIAGNOSIS]"
    )
    p = _profile(groups=_GROUPS, markers=_MARKERS)
    p["required_sections"] = _SECTIONS
    res = check_coverage(report, p)
    assert "generalization" in res.missing_sections  # prose mention does NOT count


def test_required_sections_must_be_list_of_str():
    p = _profile(groups=_GROUPS)
    p["required_sections"] = "generalization"  # not a list
    with pytest.raises(OmxError):
        check_coverage("## x", p)


# =====================================================================
# baseline regression gate — a RE-analysis must not be shallower than
# the prior report it replaces. Compares word / [FINDING] / data-table-row
# counts; a drop past tolerance is a regression (the dr_harder 2026-06-08
# incident: reports shrank 25-39% in words, 40-91% in table rows, lint
# still passed). Opt-in: only active when baseline_text is provided.
# =====================================================================
def _rich_report(n_find=10, n_rows=20, pad_words=400):
    finds = "\n".join(f"[FINDING] claim {i} [EVIDENCE: x] [CONFIDENCE: HIGH]" for i in range(n_find))
    rows = "\n".join(f"| axis{i} | {i}.0 | {i}.1 | {i}.2 |" for i in range(n_rows))
    pad = " ".join(["word"] * pad_words)
    return f"## tracking\n{finds}\n{rows}\n{pad}\n"


def test_no_baseline_text_means_no_regression_check():
    # back-compat: without a baseline, the regression gate is inert
    res = check_coverage(_rich_report(n_find=1, n_rows=1, pad_words=10),
                         _profile(groups=_GROUPS, markers=_MARKERS))
    assert res.regression is None  # not evaluated


def test_regression_flagged_when_report_shrinks():
    old = _rich_report(n_find=16, n_rows=30, pad_words=2000)
    new = _rich_report(n_find=10, n_rows=12, pad_words=1300)  # the dr_harder shrink shape
    res = check_coverage(new, _profile(groups=_GROUPS, markers=_MARKERS),
                         baseline_text=old)
    assert res.regression is not None
    assert res.regression["is_regression"] is True
    # all three axes regressed
    assert res.regression["words"]["new"] < res.regression["words"]["old"]
    assert res.regression["findings"]["new"] < res.regression["findings"]["old"]
    assert res.regression["tables"]["new"] < res.regression["tables"]["old"]
    assert res.ok is False  # regression is a hard fail


def test_no_regression_when_report_grows_or_matches():
    # isolate the regression gate: no groups/markers, so only the baseline drives ok
    old = _rich_report(n_find=10, n_rows=20, pad_words=1000)
    new = _rich_report(n_find=12, n_rows=22, pad_words=1100)  # richer rewrite
    res = check_coverage(new, _profile(), baseline_text=old)
    assert res.regression["is_regression"] is False
    assert res.ok is True


def test_regression_tolerance_allows_small_shrink():
    # default tolerance: a tiny shrink (e.g. tighter prose, same findings/tables)
    # is allowed; only a meaningful drop trips it. findings/tables held equal,
    # words down ~3% -> within tolerance. (no groups/markers -> isolate gate)
    old = _rich_report(n_find=10, n_rows=20, pad_words=1000)
    new = _rich_report(n_find=10, n_rows=20, pad_words=970)
    res = check_coverage(new, _profile(), baseline_text=old)
    assert res.regression["is_regression"] is False
    assert res.ok is True


def test_dropping_findings_is_a_regression_even_if_words_held():
    # findings/tables are stronger signals than raw words: dropping analysis units
    # is a regression even if word count is padded back up.
    old = _rich_report(n_find=16, n_rows=30, pad_words=1000)
    new = _rich_report(n_find=8, n_rows=30, pad_words=1400)  # words UP, findings HALVED
    res = check_coverage(new, _profile(groups=_GROUPS, markers=_MARKERS),
                         baseline_text=old)
    assert res.regression["is_regression"] is True
    assert res.ok is False


def test_regression_and_coverage_independent():
    # a report can pass coverage (all groups + engine) yet fail the regression gate
    old = _rich_report(n_find=16, n_rows=30, pad_words=2000)
    new_text = (
        "## tracking\n[FINDING] one [EVIDENCE: x] [CONFIDENCE: HIGH]\n"
        "| a | 1 |\n"
        "Reward/att_rp lin_vel entropy line_search_success Loss/value_function "
        "cost_value Encoder/z_std encoder_grad_norm margin/attitude "
        "doraemon_success_rate ess_ratio [DIAGNOSIS]"
    )
    res = check_coverage(new_text, _profile(groups=_GROUPS, markers=_MARKERS),
                         baseline_text=old)
    # coverage groups all referenced + engine cited -> groups/engine fine
    assert res.missing_groups == []
    assert res.engine_cited is True
    # but it shrank massively -> regression -> ok False
    assert res.regression["is_regression"] is True
    assert res.ok is False


# =====================================================================
# cross-run reference-value gate (E4 stale-teacher-column incident,
# 2026-06-08). A report often carries a cross-run reference column
# (e.g. a 'teacher hard' column in an experiment's tracking table).
# The values in that column were CARRIED FORWARD from a prior report
# and went STALE — the narrative "roll/yaw beat the teacher" was a lie
# because the teacher column no longer matched the canonical teacher
# eval. The depth/regression gate could not see this (the report grew,
# not shrank). So we add a gate over caller-supplied refs that checks
# BOTH (per the user decision "둘 다"):
#   (1) provenance: the eval id that a reference value came from
#       (static_<ts>) must be CITED in the report text — a carried-over
#       column with no citation cannot be audited;
#   (2) value match: the reported value must match the ACTUAL value in
#       that eval's summary.json (within rounding tolerance) — a stale
#       value is a hard fail.
# The fragile part (parsing the table to BUILD the refs) is the
# caller's job; this function is the pure verification engine.
# =====================================================================
def _write_summary(tmp_path, eval_id, payload):
    """Write a minimal eval summary.json under <tmp>/<eval_id>/summary.json."""
    d = tmp_path / eval_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / "summary.json"
    p.write_text(json.dumps(payload))
    return str(p)


def _teacher_payload():
    # the real teacher summary.json shape: level -> axis -> {ss_error, ...}
    return {
        "none": {"att_norm": {"ss_error": 0.5920890680847108}},
        "hard": {"att_norm": {"ss_error": 1.2833663946366705},
                 "roll": {"ss_error": 1.101}},
    }


def test_no_refs_is_a_noop_pass():
    # back-compat: no cross-run refs -> nothing to verify, vacuous pass
    res = check_cross_run_refs("any report text", [])
    assert isinstance(res, CrossRefResult)
    assert res.ok is True
    assert res.uncited == []
    assert res.mismatched == []


def test_matching_value_and_cited_eval_passes(tmp_path):
    spath = _write_summary(tmp_path, "static_260607_182214", _teacher_payload())
    report = (
        "Against the canonical teacher (eval `static_260607_182214`), att_norm hard "
        "is 1.283 for the teacher column."
    )
    refs = [{"label": "teacher hard att_norm", "summary_path": spath,
             "field": "hard/att_norm/ss_error", "reported_value": 1.283}]
    res = check_cross_run_refs(report, refs)
    assert res.ok is True
    assert res.uncited == []
    assert res.mismatched == []


def test_stale_value_is_caught(tmp_path):
    # THE incident: the report's teacher-hard column says 1.06 (a stale carried-over
    # value) but the canonical teacher eval says 1.283 -> hard fail.
    spath = _write_summary(tmp_path, "static_260607_182214", _teacher_payload())
    report = "teacher eval `static_260607_182214`; teacher hard att_norm reported 1.06."
    refs = [{"label": "teacher hard att_norm", "summary_path": spath,
             "field": "hard/att_norm/ss_error", "reported_value": 1.06}]
    res = check_cross_run_refs(report, refs)
    assert res.ok is False
    assert len(res.mismatched) == 1
    m = res.mismatched[0]
    assert m["label"] == "teacher hard att_norm"
    assert abs(m["actual"] - 1.2833663946366705) < 1e-9
    assert m["reported"] == 1.06


def test_uncited_eval_is_caught(tmp_path):
    # the reference value matches the file, BUT the report never cites the eval id
    # it came from -> provenance failure (E1/E2/E3 had teacher columns with no
    # static_<ts> citation). Must fail even though the number is correct.
    spath = _write_summary(tmp_path, "static_260607_182214", _teacher_payload())
    report = "teacher hard att_norm 1.283 (no eval id cited anywhere)."
    refs = [{"label": "teacher hard att_norm", "summary_path": spath,
             "field": "hard/att_norm/ss_error", "reported_value": 1.283}]
    res = check_cross_run_refs(report, refs)
    assert res.ok is False
    assert "teacher hard att_norm" in [u["label"] for u in res.uncited]
    # value itself matched, so it is NOT in mismatched
    assert res.mismatched == []


def test_rounding_tolerance_allows_reported_precision(tmp_path):
    # the report rounds to 3 sig figs (1.283); the file is 1.2833663...
    # this must PASS — we compare within tolerance, not exact equality.
    spath = _write_summary(tmp_path, "static_260607_182214", _teacher_payload())
    report = "eval `static_260607_182214`; teacher hard att_norm 1.283."
    refs = [{"label": "teacher hard att_norm", "summary_path": spath,
             "field": "hard/att_norm/ss_error", "reported_value": 1.283}]
    res = check_cross_run_refs(report, refs)
    assert res.ok is True
    assert res.mismatched == []


def test_small_value_uses_abs_tolerance(tmp_path):
    # yaw ss_error ~ 0.0035: a relative tolerance alone would be too strict on a
    # rounded 0.0035 vs 0.00351; abs_tol covers small magnitudes.
    payload = {"hard": {"yaw": {"ss_error": 0.00351}}}
    spath = _write_summary(tmp_path, "static_260607_182214", payload)
    report = "eval `static_260607_182214`; teacher hard yaw 0.0035."
    refs = [{"label": "teacher hard yaw", "summary_path": spath,
             "field": "hard/yaw/ss_error", "reported_value": 0.0035}]
    res = check_cross_run_refs(report, refs)
    assert res.ok is True


def test_missing_summary_file_loud_fails(tmp_path):
    report = "eval `static_260607_182214`."
    refs = [{"label": "x", "summary_path": str(tmp_path / "nope/summary.json"),
             "field": "hard/att_norm/ss_error", "reported_value": 1.0}]
    with pytest.raises(OmxError):
        check_cross_run_refs(report, refs)


def test_missing_field_path_loud_fails(tmp_path):
    # a typo'd field path must loud-fail, not silently skip the check
    spath = _write_summary(tmp_path, "static_260607_182214", _teacher_payload())
    report = "eval `static_260607_182214`."
    refs = [{"label": "x", "summary_path": spath,
             "field": "hard/att_norm/NOPE", "reported_value": 1.0}]
    with pytest.raises(OmxError):
        check_cross_run_refs(report, refs)


def test_malformed_ref_loud_fails(tmp_path):
    # a ref missing a required key must loud-fail (a typo must not disable the gate)
    spath = _write_summary(tmp_path, "static_260607_182214", _teacher_payload())
    report = "eval `static_260607_182214`."
    with pytest.raises(OmxError):
        check_cross_run_refs(report, [{"label": "x", "summary_path": spath}])


def test_eval_id_derived_from_summary_path(tmp_path):
    # the cited token is the eval-dir name (static_<ts>), derived from summary_path's
    # parent dir — so the report citing that dir name counts as provenance.
    spath = _write_summary(tmp_path, "static_260607_093844", _teacher_payload())
    report = "eval `static_260607_093844`; teacher hard att_norm 1.283."
    refs = [{"label": "teacher hard", "summary_path": spath,
             "field": "hard/att_norm/ss_error", "reported_value": 1.283}]
    res = check_cross_run_refs(report, refs)
    assert res.ok is True


def test_multiple_refs_partial_failure(tmp_path):
    # one ref stale, one ref fine -> ok False, only the stale one in mismatched
    spath = _write_summary(tmp_path, "static_260607_182214", _teacher_payload())
    report = (
        "eval `static_260607_182214`; teacher hard att_norm 1.283; "
        "teacher hard roll 9.99 (stale)."
    )
    refs = [
        {"label": "att_norm", "summary_path": spath,
         "field": "hard/att_norm/ss_error", "reported_value": 1.283},
        {"label": "roll", "summary_path": spath,
         "field": "hard/roll/ss_error", "reported_value": 9.99},  # file says 1.101
    ]
    res = check_cross_run_refs(report, refs)
    assert res.ok is False
    assert [m["label"] for m in res.mismatched] == ["roll"]
