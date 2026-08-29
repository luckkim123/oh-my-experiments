"""Unit tests for omx_paths — the OMX path single-source-of-truth.

Claude-free, Isaac-free, profile-free. Pure stdlib + pytest.
"""
import ast as _ast
from pathlib import Path

import pytest
from omx_core.omx_paths import (
    OmxPathError,
    OmxPaths,
    Profile,
    atomic_dir,
    atomic_path,
    resolve_session_id,
    validate_analysis_id,
    validate_run_id,
    validate_session_id,
    validate_token,
)


def test_error_type_is_valueerror_subclass():
    assert issubclass(OmxPathError, ValueError)


@pytest.mark.parametrize("good", ["20260530-143022-compare", "20260101-000000-next"])
def test_analysis_id_accepts_timestamped(good):
    validate_analysis_id(good)  # must not raise


@pytest.mark.parametrize("good", ["compare-20260530-143022", "diagnose-20260605-190606", "next-20260101-000000"])
def test_analysis_id_accepts_verb_first(good):
    validate_analysis_id(good)  # new label-before-date shape must not raise


@pytest.mark.parametrize("legacy", ["20260530-143022-compare", "20260101-000000-next"])
def test_analysis_id_still_accepts_legacy_date_first(legacy):
    validate_analysis_id(legacy)  # dual-accept: old on-disk dirs keep validating


@pytest.mark.parametrize("bad", [
    "2026-05-30-compare",        # wrong timestamp shape
    "20260530-143022",           # missing verb
    "20260530-143022-Compare",   # uppercase verb
    "20260530-143022-",          # empty verb
    "../escape-000000-x",        # separator/traversal
    "",
])
def test_analysis_id_rejects_bad(bad):
    with pytest.raises(OmxPathError):
        validate_analysis_id(bad)


@pytest.mark.parametrize("good", ["20260530-143022-12345", "abc-123_session.1", "uuid4formhere"])
def test_session_id_accepts(good):
    validate_session_id(good)


@pytest.mark.parametrize("bad", ["", None, "has/slash", "..", "a b"])
def test_session_id_rejects(bad):
    with pytest.raises(OmxPathError):
        validate_session_id(bad)


@pytest.mark.parametrize("good", ["r13_teacher", "260530_trpo-main", "baseline"])
def test_run_id_accepts(good):
    validate_run_id(good)


@pytest.mark.parametrize("bad", ["", "has/slash", "..", "-leading-dash", "white space"])
def test_run_id_rejects(bad):
    with pytest.raises(OmxPathError):
        validate_run_id(bad)


@pytest.mark.parametrize("good", ["ss_error", "attitude", "vx", "by_axis", "trajectory"])
def test_token_accepts(good):
    validate_token(good, "metric")


@pytest.mark.parametrize("bad", ["SS_error", "has__double", "has-dash", "", "1leadingok_butdot.no"])
def test_token_rejects(bad):
    with pytest.raises(OmxPathError):
        validate_token(bad, "metric")


def test_profile_is_frozen_with_vocab_and_optional_regex():
    p = Profile(metrics={"ss_error"}, views={"trajectory"}, aggs={"by_axis"},
                sources={"wandb"}, run_id_regex=r"^r\d+_.*$")
    assert "ss_error" in p.metrics
    with pytest.raises(Exception):
        p.metrics = {"x"}  # frozen


# --- regression: newline / control-char injection must always be rejected -----
@pytest.mark.parametrize("bad", [
    "evil\nrm", "ab\n", "\n", "a\tb", "a\rb",
])
def test_run_id_rejects_newline_injection(bad):
    with pytest.raises(OmxPathError):
        validate_run_id(bad)


@pytest.mark.parametrize("bad", ["m\n", "a\tb", "ab\n", "\n"])
def test_token_rejects_newline_injection(bad):
    with pytest.raises(OmxPathError):
        validate_token(bad, "metric")


@pytest.mark.parametrize("bad", [
    "20260530-143022-compare\n", "20260530-143022-com\npare",
])
def test_analysis_id_rejects_newline_injection(bad):
    with pytest.raises(OmxPathError):
        validate_analysis_id(bad)


def test_session_id_rejects_embedded_double_dot():
    with pytest.raises(OmxPathError):
        validate_session_id("a..b")


# --- coverage for previously-untested validators ------------------------------
def test_proposal_id_alias_matches_analysis_id():
    from omx_core.omx_paths import validate_proposal_id
    assert validate_proposal_id("20260530-143022-next") == "20260530-143022-next"
    with pytest.raises(OmxPathError):
        validate_proposal_id("bad")


@pytest.mark.parametrize("good", ["png", "csv", "parquet", "md", "json"])
def test_ext_accepts(good):
    from omx_core.omx_paths import validate_ext
    validate_ext(good)


@pytest.mark.parametrize("bad", ["PNG", "ta.r", "p ng", "", ".md"])
def test_ext_rejects(bad):
    from omx_core.omx_paths import validate_ext
    with pytest.raises(OmxPathError):
        validate_ext(bad)


def test_analysis_id_rejects_digit_only_verb():
    with pytest.raises(OmxPathError):
        validate_analysis_id("20260530-143022-123")  # verb must start with a letter


# --- I1: malformed profile run_id_regex fails loud at construction ------------
def test_profile_rejects_malformed_run_id_regex():
    with pytest.raises(OmxPathError):
        Profile(run_id_regex=r"[")  # unbalanced char class


def test_profile_accepts_valid_run_id_regex():
    p = Profile(run_id_regex=r"^r\d+_.*$")
    assert p.run_id_regex == r"^r\d+_.*$"


# =============================================================================
# Task 3: OmxPaths class — .omx/ getters with 2-tier validation
# =============================================================================


def _paths(tmp_path) -> OmxPaths:
    return OmxPaths(root=tmp_path)


def test_root_must_be_explicit_path(tmp_path):
    p = OmxPaths(root=tmp_path)
    assert p.omx_dir == Path(tmp_path) / ".omx"


def test_root_required():
    with pytest.raises(OmxPathError):
        OmxPaths(root="")


def test_omx_dir_is_anchor_not_under_output_root(tmp_path):
    p = OmxPaths(root=tmp_path)
    assert p.profile_dir == Path(tmp_path) / ".omx" / "profile"
    assert p.profile_file("metrics.yaml") == p.profile_dir / "metrics.yaml"


def test_profile_file_rejects_unknown_name(tmp_path):
    p = _paths(tmp_path)
    with pytest.raises(OmxPathError):
        p.profile_file("random.txt")


def test_run_dir_and_artifacts(tmp_path):
    p = _paths(tmp_path)
    rd = p.run_dir("r13_teacher")
    assert rd == p.omx_dir / "runs" / "r13_teacher"
    assert p.results_tsv("r13_teacher") == rd / "results.tsv"
    assert p.ledger_json("r13_teacher") == rd / "ledger.json"
    assert p.decision_log("r13_teacher") == rd / "decision-log.md"


def test_cache_path_uses_double_underscore(tmp_path):
    p = _paths(tmp_path)
    cp = p.cache_path("r13_teacher", source="wandb", metric="ss_error")
    assert cp == p.run_dir("r13_teacher") / "cache" / "wandb__ss_error.npz"


def test_cache_path_rejects_bad_token(tmp_path):
    p = _paths(tmp_path)
    with pytest.raises(OmxPathError):
        p.cache_path("r13_teacher", source="WandB", metric="ss_error")


def test_scratch_requires_session_id(tmp_path):
    p = _paths(tmp_path)
    with pytest.raises(OmxPathError):
        p.scratch_dir(session_id="")
    sd = p.scratch_dir(session_id="20260530-143022-999")
    assert sd == p.omx_dir / "scratch" / "20260530-143022-999"
    assert p.scratch_plots(session_id="20260530-143022-999") == sd / "plots"
    assert p.scratch_py(session_id="20260530-143022-999") == sd / "py"
    assert p.scratch_notes(session_id="20260530-143022-999") == sd / "notes.md"


def test_registry_and_state(tmp_path):
    p = _paths(tmp_path)
    assert p.wiki_index() == p.omx_dir / "registry" / "index.md"
    assert p.wiki_log() == p.omx_dir / "registry" / "log.md"
    assert p.wiki_lock() == p.omx_dir / "registry" / ".wiki-lock"
    assert p.wiki_dir() == p.omx_dir / "registry" / "findings"
    assert p.wiki_page("doraemon_kl") == p.omx_dir / "registry" / "findings" / "doraemon_kl.md"
    assert p.state_json() == p.omx_dir / "state.json"


def test_finding_slug_validated(tmp_path):
    p = _paths(tmp_path)
    with pytest.raises(OmxPathError):
        p.wiki_page("Bad Slug")


def test_run_id_vocab_tier_enforced_when_profile_present(tmp_path):
    prof = Profile(run_id_regex=r"\Ar\d+_.*\Z")
    p = OmxPaths(root=tmp_path, profile=prof)
    # matches profile regex -> ok
    assert p.run_dir("r13_teacher") == p.omx_dir / "runs" / "r13_teacher"
    # structurally valid but fails profile regex -> reject
    with pytest.raises(OmxPathError):
        p.run_dir("baseline")


def test_cache_metric_vocab_tier(tmp_path):
    prof = Profile(metrics={"ss_error"}, sources={"wandb"})
    p = OmxPaths(root=tmp_path, profile=prof)
    assert p.cache_path("r1", source="wandb", metric="ss_error").name == "wandb__ss_error.npz"
    with pytest.raises(OmxPathError):
        p.cache_path("r1", source="wandb", metric="attitude")  # not in profile.metrics


def test_empty_vocab_means_no_restriction(tmp_path):
    # Profile with metrics restricted but sources left empty: source is unrestricted,
    # metric is restricted (design: empty vocab set == no restriction for that field).
    prof = Profile(metrics={"ss_error"})  # sources defaults to empty frozenset
    p = OmxPaths(root=tmp_path, profile=prof)
    # arbitrary (structurally-valid) source passes because sources vocab is empty
    assert p.cache_path("r1", source="anything", metric="ss_error").name == "anything__ss_error.npz"
    # metric still restricted
    with pytest.raises(OmxPathError):
        p.cache_path("r1", source="anything", metric="vx")


@pytest.mark.parametrize("evil", ["../../etc", "..", "a/b", "a/../b", "/abs", "x\x00y"])
def test_getters_reject_traversal_end_to_end(tmp_path, evil):
    # Security property: no crafted id escapes .omx/ — getters raise before building a Path.
    p = _paths(tmp_path)
    with pytest.raises(OmxPathError):
        p.run_dir(evil)
    with pytest.raises(OmxPathError):
        p.cache_path("r1", source=evil, metric="ss_error")
    with pytest.raises(OmxPathError):
        p.wiki_page(evil)


# =============================================================================
# Task 4: permanent output-tree getters (output_root passed per-getter)
# =============================================================================
def test_analysis_tree(tmp_path):
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    a = p.analysis_dir(out, "r13_teacher", "20260530-143022-compare")
    assert a == out / "r13_teacher" / "analysis" / "20260530-143022-compare"
    assert p.report_md(out, "r13_teacher", "20260530-143022-compare") == a / "report.md"
    assert p.report_ko_md(out, "r13_teacher", "20260530-143022-compare") == a / "report.ko.md"
    assert p.manifest_json(out, "r13_teacher", "20260530-143022-compare") == a / "manifest.json"


def test_report_ko_md_verb_first(tmp_path):
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    a = p.analysis_dir(out, "r13_teacher", "diagnose-20260605-190606")
    assert p.report_ko_md(out, "r13_teacher", "diagnose-20260605-190606") == a / "report.ko.md"
    assert p.report_ko_md(out, "r13_teacher", "diagnose-20260605-190606").name == "report.ko.md"


def test_analysis_plot_uses_metric_view(tmp_path):
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    plot = p.analysis_plot(out, "r13_teacher", "20260530-143022-compare",
                           metric="attitude", view="trajectory")
    assert plot.name == "attitude__trajectory.png"
    assert plot.parent.name == "plots"


def test_analysis_table_uses_metric_agg(tmp_path):
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    tbl = p.analysis_table(out, "r13_teacher", "20260530-143022-compare",
                           metric="ss_error", agg="by_axis")
    assert tbl.name == "ss_error__by_axis.csv"
    assert tbl.parent.name == "tables"


def test_proposal_path(tmp_path):
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    pr = p.proposal_md(out, "r13_teacher", "20260530-143022-next")
    assert pr == out / "r13_teacher" / "proposals" / "20260530-143022-next.md"


# --- grouped run layout: output_root/<group>/<run_id>/... (e.g. rsl_rl/<exp>/dr_harder) ---
def test_analysis_tree_grouped(tmp_path):
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    grp = "rsl_rl/albc_trpo_teacher/dr_harder"
    a = p.analysis_dir(out, "trpo_e1_260605", "20260530-143022-compare", group=grp)
    assert a == out / grp / "trpo_e1_260605" / "analysis" / "20260530-143022-compare"
    assert p.report_md(out, "trpo_e1_260605", "20260530-143022-compare", group=grp) == a / "report.md"
    assert p.report_ko_md(out, "trpo_e1_260605", "20260530-143022-compare", group=grp) == a / "report.ko.md"
    assert p.manifest_json(out, "trpo_e1_260605", "20260530-143022-compare", group=grp) == a / "manifest.json"


def test_grouped_plot_and_table(tmp_path):
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    grp = "rsl_rl/albc_trpo_teacher/dr_harder"
    plot = p.analysis_plot(out, "r1", "20260530-143022-x", metric="ss_error", view="trajectory", group=grp)
    assert plot == out / grp / "r1" / "analysis" / "20260530-143022-x" / "plots" / "ss_error__trajectory.png"
    tbl = p.analysis_table(out, "r1", "20260530-143022-x", metric="ss_error", agg="by_axis", group=grp)
    assert tbl == out / grp / "r1" / "analysis" / "20260530-143022-x" / "tables" / "ss_error__by_axis.csv"


def test_grouped_proposal(tmp_path):
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    grp = "rsl_rl/albc_trpo_teacher/dr_harder"
    pr = p.proposal_md(out, "r1", "20260530-143022-next", group=grp)
    assert pr == out / grp / "r1" / "proposals" / "20260530-143022-next.md"


def test_group_none_is_flat_backcompat(tmp_path):
    # group omitted / None / "" must reproduce the existing flat layout exactly.
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    flat = p.analysis_dir(out, "r13_teacher", "20260530-143022-compare")
    assert p.analysis_dir(out, "r13_teacher", "20260530-143022-compare", group=None) == flat
    assert p.analysis_dir(out, "r13_teacher", "20260530-143022-compare", group="") == flat
    assert flat == out / "r13_teacher" / "analysis" / "20260530-143022-compare"


@pytest.mark.parametrize("evil_group", ["../escape", "a/../b", "/abs/path", "a//b", "a/..", ".."])
def test_grouped_rejects_traversal(tmp_path, evil_group):
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    with pytest.raises(OmxPathError):
        p.analysis_dir(out, "r1", "20260530-143022-compare", group=evil_group)


def test_group_segment_charset_enforced(tmp_path):
    # each segment obeys the run_id charset (alnum/_/-); a bad char is rejected.
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    with pytest.raises(OmxPathError):
        p.analysis_dir(out, "r1", "20260530-143022-compare", group="ok/bad seg")


def test_bad_analysis_id_rejected_in_tree(tmp_path):
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    with pytest.raises(OmxPathError):
        p.report_md(out, "r13_teacher", "not-a-valid-id")


@pytest.mark.parametrize("bad_root", ["", None])
def test_output_root_required(tmp_path, bad_root):
    p = _paths(tmp_path)
    with pytest.raises(OmxPathError):
        p.analysis_dir(bad_root, "r13_teacher", "20260530-143022-compare")


def test_analysis_table_rejects_bad_token(tmp_path):
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    with pytest.raises(OmxPathError):
        p.analysis_table(out, "r1", "20260530-143022-x", metric="SS_error", agg="by_axis")
    with pytest.raises(OmxPathError):
        p.analysis_table(out, "r1", "20260530-143022-x", metric="ss_error", agg="bad-agg")


def test_vocabulary_tier_enforced_in_permanent_tree(tmp_path):
    prof = Profile(metrics={"ss_error"}, views={"trajectory"})
    p = OmxPaths(root=tmp_path, profile=prof)
    out = tmp_path / "experiments"
    with pytest.raises(OmxPathError):
        p.analysis_plot(out, "r13_teacher", "20260530-143022-compare",
                        metric="attitude", view="trajectory")  # metric not in vocab
    ok = p.analysis_plot(out, "r13_teacher", "20260530-143022-compare",
                         metric="ss_error", view="trajectory")
    assert ok.name == "ss_error__trajectory.png"


def test_run_id_vocab_tier_in_permanent_tree(tmp_path):
    prof = Profile(run_id_regex=r"\Ar\d+_.*\Z")
    p = OmxPaths(root=tmp_path, profile=prof)
    out = tmp_path / "experiments"
    with pytest.raises(OmxPathError):
        p.analysis_dir(out, "baseline", "20260530-143022-compare")  # run_id fails profile regex
    assert p.analysis_dir(out, "r1_x", "20260530-143022-compare").parts[-3] == "r1_x"


@pytest.mark.parametrize("evil", ["../../etc", "..", "a/b"])
def test_permanent_tree_rejects_traversal(tmp_path, evil):
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    with pytest.raises(OmxPathError):
        p.analysis_dir(out, evil, "20260530-143022-compare")  # bad run_id
    with pytest.raises(OmxPathError):
        p.proposal_md(out, "r1", evil + "-000000-x")  # bad proposal_id


# =============================================================================
# Task 5: resolve_session_id (B2 precedence) + atomic write helpers
# =============================================================================


def test_resolve_session_id_prefers_explicit():
    assert resolve_session_id(explicit="abc-1", env=None, autogen=lambda: "GEN") == "abc-1"


def test_resolve_session_id_falls_back_to_env():
    assert resolve_session_id(explicit=None, env="env-sid", autogen=lambda: "GEN") == "env-sid"


def test_resolve_session_id_autogens_last():
    assert resolve_session_id(explicit=None, env=None,
                              autogen=lambda: "20260530-143022-77") == "20260530-143022-77"


def test_resolve_session_id_empty_explicit_falls_through():
    # empty string is falsy -> should fall through to env, then autogen
    assert resolve_session_id(explicit="", env="", autogen=lambda: "gen-1") == "gen-1"


def test_resolve_session_id_validates_result():
    with pytest.raises(OmxPathError):
        resolve_session_id(explicit="has/slash", env=None, autogen=lambda: "x")


def test_resolve_session_id_validates_autogen_output():
    with pytest.raises(OmxPathError):
        resolve_session_id(explicit=None, env=None, autogen=lambda: "bad/sid")


def test_resolve_session_id_raises_when_nothing_resolves():
    with pytest.raises(OmxPathError):
        resolve_session_id(explicit=None, env=None, autogen=None)


# =============================================================================
# Task 1: pending_launch_json run-tree getter (B8 launch queue)
# =============================================================================
def test_pending_launch_json_under_run_dir(tmp_path):
    p = OmxPaths(root=tmp_path)
    target = p.pending_launch_json("run-42")
    assert target.name == "pending-launch.json"
    assert target.parent == p.run_dir("run-42")


def test_pending_launch_json_validates_run_id(tmp_path):
    p = OmxPaths(root=tmp_path)
    with pytest.raises(OmxPathError):
        p.pending_launch_json("../escape")


def test_atomic_path_writes_via_tmp_then_replaces(tmp_path):
    target = tmp_path / "out" / "report.md"
    with atomic_path(target) as tmp:
        assert tmp != target
        assert tmp.name.endswith(".tmp")
        tmp.write_text("hello")
        assert not target.exists()  # not yet committed
    assert target.read_text() == "hello"  # committed on clean exit


def test_atomic_path_discards_on_exception(tmp_path):
    target = tmp_path / "out" / "report.md"
    with pytest.raises(RuntimeError):
        with atomic_path(target) as tmp:
            tmp.write_text("partial")
            raise RuntimeError("boom")
    assert not target.exists()                       # partial never promoted
    assert list((tmp_path / "out").glob("*.tmp")) == []  # no stray .tmp


def test_atomic_dir_promotes_on_success(tmp_path):
    target = tmp_path / "out" / "analysis_x"
    with atomic_dir(target) as tmp:
        (tmp / "report.md").write_text("r")
        assert not target.exists()
    assert (target / "report.md").read_text() == "r"


def test_atomic_dir_discards_on_exception(tmp_path):
    target = tmp_path / "out" / "analysis_x"
    with pytest.raises(RuntimeError):
        with atomic_dir(target) as tmp:
            (tmp / "report.md").write_text("partial")
            raise RuntimeError("boom")
    assert not target.exists()


def test_atomic_path_cleans_up_on_baseexception(tmp_path):
    # BaseException (e.g. KeyboardInterrupt) must also clean up, not just Exception.
    target = tmp_path / "out" / "f.md"
    with pytest.raises(KeyboardInterrupt):
        with atomic_path(target) as tmp:
            tmp.write_text("partial")
            raise KeyboardInterrupt
    assert not target.exists()
    assert list((tmp_path / "out").glob("*.tmp")) == []


def test_atomic_dir_cleans_up_on_baseexception(tmp_path):
    target = tmp_path / "out" / "d"
    with pytest.raises(KeyboardInterrupt):
        with atomic_dir(target) as tmp:
            (tmp / "x").write_text("partial")
            raise KeyboardInterrupt
    assert not target.exists()
    assert list((tmp_path / "out").glob("*.tmp")) == []


# =============================================================================
# Task 6: completeness gate — every public path getter must be exercised
# =============================================================================
def _ref_eval_path(p):
    """Exercise reference_evaluator and always return a Path.

    The committed reference .sh ships in build-order #2 Task 6; until then the
    getter loud-fails (OmxPathError, file absent). This wrapper calls the getter
    in both states and returns a Path so the completeness guard can verify the
    getter is registered without depending on the file's presence."""
    from omx_core.omx_paths import OmxPathError
    try:
        return p.reference_evaluator("isaaclab")
    except OmxPathError:
        return p.reference_dir / "isaaclab" / "evaluator.sh"


def test_every_public_path_getter_is_exercised(tmp_path):
    """Guard: enumerate OmxPaths path-returning methods; ensure each is callable
    with a minimal valid arg set and returns a Path. Fails if a getter is added
    later without being added here (and given its own dedicated test above)."""
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    rid, aid, pid, sid = "r1", "20260530-143022-x", "20260530-143022-next", "s-1"
    calls = {
        "profile_file": lambda: p.profile_file("metrics.yaml"),
        "seal_json": lambda: p.seal_json(),
        "tree_yaml": lambda: p.tree_yaml(),
        "run_dir": lambda: p.run_dir(rid),
        "results_tsv": lambda: p.results_tsv(rid),
        "ledger_json": lambda: p.ledger_json(rid),
        "decision_log": lambda: p.decision_log(rid),
        "cache_path": lambda: p.cache_path(rid, source="wandb", metric="ss_error"),
        "scratch_dir": lambda: p.scratch_dir(session_id=sid),
        "scratch_plots": lambda: p.scratch_plots(session_id=sid),
        "scratch_py": lambda: p.scratch_py(session_id=sid),
        "scratch_notes": lambda: p.scratch_notes(session_id=sid),
        "wiki_index": lambda: p.wiki_index(),
        "wiki_log": lambda: p.wiki_log(),
        "wiki_lock": lambda: p.wiki_lock(),
        "wiki_dir": lambda: p.wiki_dir(),
        "wiki_page": lambda: p.wiki_page("slug1"),
        "state_json": lambda: p.state_json(),
            "produced_reports_ledger": lambda: p.produced_reports_ledger(),
            "profile_projection": lambda: p.profile_projection(),
            "recipes_dir": lambda: p.recipes_dir(),
        # reference_evaluator loud-fails until Task 6 ships the .sh; exercise the
        # getter and accept either the resolved Path (Task 6 state) or the
        # absent-file loud-fail (Task 1 state), returning a Path either way.
        "reference_evaluator": lambda: _ref_eval_path(p),
        "checkpoint_pointer_json": lambda: p.checkpoint_pointer_json(rid),
        "pending_launch_json": lambda: p.pending_launch_json(rid),
        "loop_lock": lambda: p.loop_lock(rid),
        "state_lock": lambda: p.state_lock(),
        "trash_root": lambda: p.trash_root(),
        "loop_marker_json": lambda: p.loop_marker_json(rid),
        "campaign_dir": lambda: p.campaign_dir("camp_a"),
        "campaign_plan": lambda: p.campaign_plan("camp_a"),
        "campaign_ledger": lambda: p.campaign_ledger("camp_a"),
        "campaigns_root": lambda: p.campaigns_root(),
        "program_dir": lambda: p.program_dir("prog_a"),
        "program_json": lambda: p.program_json("prog_a"),
        "program_plan_md": lambda: p.program_plan_md("prog_a"),
        "programs_root": lambda: p.programs_root(),
        "runs_root": lambda: p.runs_root(),
        "analysis_dir": lambda: p.analysis_dir(out, rid, aid),
        "report_md": lambda: p.report_md(out, rid, aid),
        "report_ko_md": lambda: p.report_ko_md(out, rid, aid),
        "manifest_json": lambda: p.manifest_json(out, rid, aid),
        "analysis_plot": lambda: p.analysis_plot(out, rid, aid, metric="m", view="v"),
        "analysis_table": lambda: p.analysis_table(out, rid, aid, metric="m", agg="a"),
        "proposal_md": lambda: p.proposal_md(out, rid, pid),
    }
    # Stage 2: every getter, including the enumeration-root getters, returns
    # a single resolved Path — no more (new, legacy) tuples.
    for name, fn in calls.items():
        result = fn()
        assert isinstance(result, Path), f"{name} did not return a Path"

    # Discover public callables on the instance; every path getter must be in `calls`.
    # Excludes: properties handled separately (profile_dir), non-path attrs (root,
    # profile, omx_dir), and any dunder.
    EXCLUDE = {"profile_dir", "root", "profile", "omx_dir"}
    public_callables = {
        n for n in dir(p)
        if not n.startswith("_")
        and callable(getattr(p, n))
        and n not in EXCLUDE
    }
    untested = public_callables - set(calls)
    assert not untested, f"new getter(s) without coverage in the guard: {untested}"

    # profile_dir is a property (not callable) — assert it's a Path explicitly.
    assert isinstance(p.profile_dir, Path)


def test_public_import_surface_from_package_root():
    """Run-from-anywhere sanity: the documented public API imports from omx_core."""
    import omx_core
    for name in [
        "OmxPaths", "Profile", "OmxPathError",
        "validate_analysis_id", "validate_proposal_id", "validate_session_id",
        "validate_run_id", "validate_token", "validate_ext",
        "resolve_session_id", "atomic_path", "atomic_dir",
    ]:
        assert hasattr(omx_core, name), f"omx_core is missing public export: {name}"


def test_atomic_dir_failed_promotion_leaves_no_tmp(tmp_path):
    # os.replace onto a non-empty existing target raises Errno 39; the .tmp dir
    # must NOT leak (the os.replace in the else-branch is exception-guarded).
    target = tmp_path / "out" / "d"
    target.mkdir(parents=True)
    (target / "old.md").write_text("old")  # pre-existing non-empty target
    with pytest.raises(OSError):
        with atomic_dir(target) as tmp:
            (tmp / "new.md").write_text("new")
    # original target untouched, no stray .tmp left behind
    assert (target / "old.md").read_text() == "old"
    assert list((tmp_path / "out").glob("*.tmp")) == []


def test_cache_path_uses_npz_extension(tmp_path):
    from omx_core.omx_paths import OmxPaths
    p = OmxPaths(tmp_path)
    out = p.cache_path("run01", source="eval_summary", metric="ss_error")
    assert out.name == "eval_summary__ss_error.npz"
    assert out.suffix == ".npz"


def test_omx_error_is_base_of_path_error():
    from omx_core.omx_paths import OmxError, OmxPathError
    assert issubclass(OmxPathError, OmxError)
    assert issubclass(OmxPathError, ValueError)  # legacy except-sites still catch it


def test_reference_dir_is_packaged(tmp_path):
    from omx_core.omx_paths import OmxPaths
    p = OmxPaths(tmp_path)
    rd = p.reference_dir
    assert rd.name == "reference"
    assert rd.parent.name == "omx_core"
    assert tmp_path not in rd.parents  # anchored to the install, never under the per-run root


def test_reference_evaluator_rejects_bad_profile(tmp_path):
    import pytest
    from omx_core.omx_paths import OmxPathError, OmxPaths
    p = OmxPaths(tmp_path)
    with pytest.raises(OmxPathError):
        p.reference_evaluator("Isaac Lab")  # space -> not a token


def test_reference_evaluator_loud_fails_when_absent(tmp_path):
    # The committed .sh ships in Task 6. Until then the getter must LOUD-FAIL
    # (not silently return a non-existent path). This is a strict assertion now,
    # and Task 6 re-asserts the resolves-success case once the file exists.
    import pytest
    from omx_core.omx_paths import OmxPathError, OmxPaths
    p = OmxPaths(tmp_path)
    ref = p.reference_dir / "isaaclab" / "evaluator.sh"
    if ref.exists():
        import pytest as _pt
        _pt.skip("reference shipped (Task 6 done); resolves-success covered there")
    with pytest.raises(OmxPathError) as ei:
        p.reference_evaluator("isaaclab")
    assert "not shipped" in str(ei.value)


def test_checkpoint_pointer_json_under_run(tmp_path):
    from omx_core.omx_paths import OmxPaths
    p = OmxPaths(tmp_path)
    cp = p.checkpoint_pointer_json("run01")
    assert cp == p.run_dir("run01") / "checkpoint-pointer.json"


# =============================================================================
# .hq/ cutover (om* store unification P6) — new-vs-legacy resolution
# =============================================================================

def _anchor(root, anchor_id="test-anchor"):
    """Write a parseable .hq/.anchor under `root` (store-spec §2 shape)."""
    from omx_core.omx_paths import anchor_file
    f = anchor_file(root)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f"id: {anchor_id}\n", encoding="utf-8")
    return f


# --- gate_state(): the four states -------------------------------------------

def test_gate_state_off_no_legacy_no_anchor(tmp_path):
    from omx_core.omx_paths import GATE_OFF, gate_state
    assert gate_state(tmp_path) == GATE_OFF


def test_gate_state_legacy_store_present_no_anchor(tmp_path):
    from omx_core.omx_paths import GATE_LEGACY, gate_state
    (tmp_path / ".omx").mkdir()
    assert gate_state(tmp_path) == GATE_LEGACY


def test_gate_state_normal_anchor_present_and_parseable(tmp_path):
    from omx_core.omx_paths import GATE_NORMAL, gate_state
    _anchor(tmp_path)
    assert gate_state(tmp_path) == GATE_NORMAL


@pytest.mark.parametrize("bad_content", [
    "id: a\nid: b\n",   # two non-empty lines (spec: duplicate id shape)
    "not-an-id-line\n",  # missing 'id:' prefix
    "id: \n",            # empty value
    "",                  # empty file entirely
])
def test_gate_state_corrupt_anchor(tmp_path, bad_content):
    from omx_core.omx_paths import GATE_CORRUPT, anchor_file, gate_state
    f = anchor_file(tmp_path)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(bad_content, encoding="utf-8")
    assert gate_state(tmp_path) == GATE_CORRUPT


def test_has_anchor_false_on_corrupt(tmp_path):
    from omx_core.omx_paths import anchor_file, has_anchor
    f = anchor_file(tmp_path)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("garbage\n", encoding="utf-8")
    assert has_anchor(tmp_path) is False


def test_parse_anchor_id_returns_value(tmp_path):
    from omx_core.omx_paths import parse_anchor_id
    f = _anchor(tmp_path, anchor_id="my-anchor-id")
    assert parse_anchor_id(f) == "my-anchor-id"


def test_parse_anchor_id_raises_anchor_error_on_bad_shape(tmp_path):
    from omx_core.omx_paths import AnchorError, anchor_file, parse_anchor_id
    f = anchor_file(tmp_path)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("no id prefix here\n", encoding="utf-8")
    with pytest.raises(AnchorError):
        parse_anchor_id(f)


# --- _resolve(): the anchor alone decides, in both directions (stage 2) -----
# store-spec §7 stage 2: no per-file fallback window, no existence check.
# These are the team-lead-specified regression pair: (a) an anchored project
# whose entity exists ONLY at legacy still resolves to .hq/ — the exact case
# stage 1's _write() used to protect by staying on legacy; (b) an unanchored
# project keeps resolving to legacy regardless of what's on disk.

def test_resolve_anchored_ignores_existing_legacy_content(tmp_path):
    from omx_core.omx_paths import _resolve
    legacy = tmp_path / "legacy-path"
    legacy.mkdir()
    _anchor(tmp_path)
    new = tmp_path / "new-path"
    assert _resolve(tmp_path, new, legacy) == new


def test_resolve_unanchored_with_legacy_content_stays_legacy(tmp_path):
    from omx_core.omx_paths import _resolve
    legacy = tmp_path / "legacy-path"
    legacy.mkdir()
    new = tmp_path / "new-path"
    assert _resolve(tmp_path, new, legacy) == legacy


# --- getter resolution: legacy (no anchor) vs new (anchor) -------------------
# Every base-directory getter must (a) resolve to the SAME .omx/ path as
# before when no anchor exists, and (b) resolve under .hq/ once anchored —
# unconditionally now, existence on disk no longer matters (stage 2).

@pytest.mark.parametrize("getter_name,call,new_suffix", [
    ("profile_dir", lambda p: p.profile_dir, ("config", "experiments", "profile")),
    ("run_dir", lambda p: p.run_dir("r1"), ("work", "experiments", "runs", "r1")),
    ("scratch_dir", lambda p: p.scratch_dir(session_id="s1"),
     ("runtime", "experiments", "scratch", "s1")),
    ("wiki_dir", lambda p: p.wiki_dir(), ("community", "wiki")),
    ("wiki_index", lambda p: p.wiki_index(), ("community", "wiki", "index.md")),
    ("wiki_log", lambda p: p.wiki_log(),
     ("runtime", "experiments", "registry", "log.md")),
    ("wiki_lock", lambda p: p.wiki_lock(), ("community", "wiki", ".wiki-lock")),
    ("recipes_dir", lambda p: p.recipes_dir(), ("community", "recipes")),
    ("state_json", lambda p: p.state_json(), ("runtime", "experiments", "state.json")),
    ("produced_reports_ledger", lambda p: p.produced_reports_ledger(),
     ("config", "experiments", "produced-reports.jsonl")),
    ("state_lock", lambda p: p.state_lock(),
     ("runtime", "experiments", "state", ".state-lock")),
    ("campaign_dir", lambda p: p.campaign_dir("camp1"),
     ("work", "experiments", "campaigns", "camp1")),
    ("program_dir", lambda p: p.program_dir("prog1"),
     ("community", "programs", "prog1")),
    ("program_json", lambda p: p.program_json("prog1"),
     ("config", "experiments", "programs", "prog1", "program.json")),
    ("campaigns_root", lambda p: p.campaigns_root(),
     ("work", "experiments", "campaigns")),
    ("programs_root", lambda p: p.programs_root(), ("community", "programs")),
    ("runs_root", lambda p: p.runs_root(), ("work", "experiments", "runs")),
])
def test_getter_resolves_new_on_fresh_anchored_entity(tmp_path, getter_name, call, new_suffix):
    from omx_core.omx_paths import HQ_ROOT
    p = _paths(tmp_path)
    _anchor(tmp_path)
    result = call(p)
    assert result == Path(tmp_path, HQ_ROOT, *new_suffix), (
        f"{getter_name}: expected .hq/ resolution for a brand-new anchored "
        f"entity, got {result}")


@pytest.mark.parametrize("getter_name,call,legacy_suffix", [
    ("profile_dir", lambda p: p.profile_dir, ("profile",)),
    ("run_dir", lambda p: p.run_dir("r1"), ("runs", "r1")),
    ("scratch_dir", lambda p: p.scratch_dir(session_id="s1"), ("scratch", "s1")),
    ("wiki_dir", lambda p: p.wiki_dir(), ("registry", "findings")),
    ("wiki_index", lambda p: p.wiki_index(), ("registry", "index.md")),
    ("wiki_log", lambda p: p.wiki_log(), ("registry", "log.md")),
    ("wiki_lock", lambda p: p.wiki_lock(), ("registry", ".wiki-lock")),
    ("recipes_dir", lambda p: p.recipes_dir(), ("recipes",)),
    ("state_json", lambda p: p.state_json(), ("state.json",)),
    ("produced_reports_ledger", lambda p: p.produced_reports_ledger(),
     ("state", "produced-reports.jsonl")),
    ("state_lock", lambda p: p.state_lock(), ("state", ".state-lock")),
    ("campaign_dir", lambda p: p.campaign_dir("camp1"), ("campaigns", "camp1")),
    ("program_dir", lambda p: p.program_dir("prog1"), ("programs", "prog1")),
    ("program_json", lambda p: p.program_json("prog1"),
     ("programs", "prog1", "program.json")),
    ("campaigns_root", lambda p: p.campaigns_root(), ("campaigns",)),
    ("programs_root", lambda p: p.programs_root(), ("programs",)),
    ("runs_root", lambda p: p.runs_root(), ("runs",)),
])
def test_getter_falls_back_to_legacy_when_no_anchor(tmp_path, getter_name, call, legacy_suffix):
    p = _paths(tmp_path)
    result = call(p)
    assert result == Path(tmp_path, ".omx", *legacy_suffix), (
        f"{getter_name}: expected .omx/ fallback with no anchor, got {result}")


def test_getter_ignores_existing_legacy_content_once_anchored(tmp_path):
    """Stage 2 regression guard at the getter level (mirrors the bare
    _resolve() pair above): an anchored project resolves campaign_dir() to
    .hq/ even when the entity exists ONLY at legacy — no more split-brain
    protection via per-file fallback."""
    p = _paths(tmp_path)
    (tmp_path / ".omx" / "campaigns" / "camp1").mkdir(parents=True)
    _anchor(tmp_path)
    from omx_core.omx_paths import HQ_ROOT
    assert p.campaign_dir("camp1") == Path(
        tmp_path, HQ_ROOT, "work", "experiments", "campaigns", "camp1")


def test_wiki_lock_not_split_from_wiki_dir_new(tmp_path):
    """wiki_lock() must land inside wiki_dir()'s OWN resolved directory once
    anchored (both resolve under community/wiki/ in the new layout)."""
    p = _paths(tmp_path)
    _anchor(tmp_path)
    assert p.wiki_lock().parent == p.wiki_dir()


def test_program_dir_and_program_json_split_across_layers(tmp_path):
    """program_dir() (community/ narrative) and program_json() (config/
    header) must resolve to DIFFERENT directories once anchored, per the
    mapping table split."""
    p = _paths(tmp_path)
    _anchor(tmp_path)
    d = p.program_dir("prog1")
    pj = p.program_json("prog1")
    assert d != pj.parent
    assert "community" in d.parts
    assert "config" in pj.parts
    assert p.program_plan_md("prog1") == d / "PLAN.md"


def test_reference_dir_unaffected_by_anchor(tmp_path):
    """reference_dir is anchored to the installed package, never to root —
    an anchor at root must not perturb it."""
    p = _paths(tmp_path)
    before = p.reference_dir
    _anchor(tmp_path)
    assert p.reference_dir == before


# --- iter_store_entries() and the *_root() enumeration getters (stage 2) ----
# An anchored project has exactly one enumeration root, not a union of two —
# campaigns_root()/programs_root()/runs_root() now return a single resolved
# Path (same _resolve() as every entity getter), folded into the same
# new_suffix/legacy_suffix parametrize tables above (search "campaigns_root").

def test_iter_store_entries_empty_when_root_missing(tmp_path):
    from omx_core.omx_paths import iter_store_entries
    assert iter_store_entries(tmp_path / "absent") == {}


def test_iter_store_entries_lists_children_keyed_by_name(tmp_path):
    from omx_core.omx_paths import iter_store_entries
    root = tmp_path / "campaigns"
    (root / "camp1").mkdir(parents=True)
    (root / "camp2").mkdir(parents=True)
    entries = iter_store_entries(root)
    assert entries == {"camp1": root / "camp1", "camp2": root / "camp2"}


def test_trash_root_no_leading_dot_on_new_no_anchor_stays_legacy(tmp_path):
    """runtime/ is already .gitignore'd wholesale, so the new-layout trash
    child drops the leading dot (unlike the .omx/.trash legacy name).
    _resolve()-resolved like every other getter: no anchor -> legacy dotted
    name unchanged."""
    p = _paths(tmp_path)
    assert p.trash_root() == tmp_path / ".omx" / ".trash"


def test_trash_root_resolves_new_when_anchored(tmp_path):
    from omx_core.omx_paths import HQ_ROOT
    p = _paths(tmp_path)
    _anchor(tmp_path)
    assert p.trash_root() == Path(tmp_path, HQ_ROOT, "runtime", "experiments", "trash")


def test_getters_still_validate_before_resolving_when_anchored(tmp_path):
    """Validation (loud-fail on bad ids) must fire before any new/legacy
    resolution happens, anchored or not."""
    p = _paths(tmp_path)
    _anchor(tmp_path)
    with pytest.raises(OmxPathError):
        p.run_dir("../escape")
    with pytest.raises(OmxPathError):
        p.campaign_dir("has/slash")
    with pytest.raises(OmxPathError):
        p.program_dir("..")
    with pytest.raises(OmxPathError):
        p.scratch_dir(session_id="")


def test_has_store_and_has_legacy_store(tmp_path):
    from omx_core.omx_paths import has_legacy_store, has_store
    assert has_store(tmp_path) is False
    assert has_legacy_store(tmp_path) is False
    (tmp_path / ".omx").mkdir()
    assert has_legacy_store(tmp_path) is True
    assert has_store(tmp_path) is True


def test_has_store_true_on_anchor_alone(tmp_path):
    from omx_core.omx_paths import has_legacy_store, has_store
    _anchor(tmp_path)
    assert has_legacy_store(tmp_path) is False
    assert has_store(tmp_path) is True


# --- re-entry lint: no stray .hq/.omx literal outside omx_paths.py ----------
# Mirrors oh-my-project/tests/test_omp_paths_lint.py (the reference this repo
# was told to copy). AST-based, not regex-on-text: a str Constant (f-string
# pieces included, via ast.walk descending into JoinedStr) counts as a
# violation iff it CONTAINS the root literal AND has no whitespace anywhere —
# paths never have spaces, prose always does. Module/function/class docstrings
# (the first statement) are exempt.

def _lint_roots():
    from omx_core.omx_paths import HQ_ROOT, LEGACY_ROOT
    return (LEGACY_ROOT, HQ_ROOT)


def _lint_repo_root() -> Path:
    # this file: omx-core/tests/test_omx_paths.py -> repo root is 2 parents up
    return Path(__file__).resolve().parent.parent.parent


def _lint_paths_module() -> Path:
    return _lint_repo_root() / "omx-core" / "omx_core" / "omx_paths.py"


# Files/dirs exempt beyond the paths module itself, each with a stated reason:
#   - any path component "tests" or "fixtures": fixtures legitimately build
#     .omx/... paths on disk (mirrors omp's tests/ exclusion; omx nests its
#     tests one level deeper at omx-core/tests/, not at the repo root).
#   - "reference" under omx_core: the shipped reference/ package copied into
#     a user's .omx/profile/ by exp-init — same class as omp's references/
#     exclusion (content, not a resolution site).
#   - hooks/handlers.py: a single, documented exception — _has_omx_marker
#     must stay import-free (test_handlers_import_without_omx_core poisons
#     omx_core entirely and still requires this probe to work) and hot-path
#     cheap, so it keeps its own literal rather than importing LEGACY_ROOT.
#   - omx_core/root.py: MARKER = ".omx-workspace" is a DIFFERENT concept — a
#     multi-repo workspace-root marker climbed by the #13 resolution ladder,
#     unrelated to the .hq/.omx STORE this module resolves. It only trips the
#     lint because ".omx-workspace" contains the substring ".omx" (the lint's
#     own rule is substring-based, matching omp's). Renaming it or routing it
#     through omx_paths.py is out of scope for this port — it is not one of
#     the mapped artifacts.
_LINT_EXCLUDED_DIR_PARTS = {"tests", "fixtures", "reference", "__pycache__",
                           ".git", ".pytest_cache", "egg-info"}
_LINT_EXCLUDED_FILES = {("hooks", "handlers.py"), ("omx-core", "omx_core", "root.py")}


def _lint_is_violation(value: str) -> bool:
    return any(r in value for r in _lint_roots()) and not any(ch.isspace() for ch in value)


def _lint_docstring_constant_ids(tree: _ast.AST) -> set:
    ids = set()
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Module, _ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], _ast.Expr)
                    and isinstance(body[0].value, _ast.Constant)
                    and isinstance(body[0].value.value, str)):
                ids.add(id(body[0].value))
    return ids


def _lint_violations_in_source(source: str, filename: str = "<string>") -> list:
    tree = _ast.parse(source, filename=filename)
    skip = _lint_docstring_constant_ids(tree)
    out = []
    for node in _ast.walk(tree):
        if (isinstance(node, _ast.Constant) and isinstance(node.value, str)
                and id(node) not in skip and _lint_is_violation(node.value)):
            out.append((node.lineno, node.value))
    return out


def _lint_scanned_files():
    repo_root = _lint_repo_root()
    paths_module = _lint_paths_module()
    for path in sorted(repo_root.rglob("*.py")):
        rel = path.relative_to(repo_root)
        if any(part in _LINT_EXCLUDED_DIR_PARTS for part in rel.parts[:-1]):
            continue
        if tuple(rel.parts) in _LINT_EXCLUDED_FILES:
            continue
        if path == paths_module:
            continue
        yield path


def test_lint_scan_targets_exist():
    assert list(_lint_scanned_files()), "no .py files found to scan — lint scope is broken"


def test_no_root_literal_reentry():
    offenders = []
    repo_root = _lint_repo_root()
    for path in _lint_scanned_files():
        rel = path.relative_to(repo_root)
        for lineno, value in _lint_violations_in_source(path.read_text(encoding="utf-8"), str(rel)):
            offenders.append(f"{rel}:{lineno}: {value!r}")
    assert not offenders, (
        "new " + " or ".join(repr(r) for r in _lint_roots())
        + " literal(s) outside omx-core/omx_core/omx_paths.py — "
        "add a named helper there instead:\n" + "\n".join(offenders)
    )


def test_lint_meta_bare_literal_bites():
    v = _lint_violations_in_source('X = ".omx"\n')
    assert v == [(1, ".omx")]


def test_lint_meta_path_literal_bites():
    v = _lint_violations_in_source('X = ".omx/state.json"\n')
    assert len(v) == 1 and v[0][1] == ".omx/state.json"


def test_lint_meta_fstring_piece_bites():
    v = _lint_violations_in_source('name = "x"\nX = f".omx/{name}.md"\n')
    assert any(".omx/" in val for _, val in v)


def test_lint_meta_prose_with_whitespace_is_not_a_violation():
    v = _lint_violations_in_source('X = ".omx/state.json 갱신은 이 작업의 일부"\n')
    assert v == []


def test_lint_meta_module_docstring_is_exempt():
    v = _lint_violations_in_source('""".omx/state.json is the SSOT."""\nX = 1\n')
    assert v == []


def test_lint_meta_function_docstring_is_exempt():
    v = _lint_violations_in_source('def f():\n    """.omx/wiki holds notes."""\n    return 1\n')
    assert v == []


def test_lint_meta_hq_literal_bites():
    v = _lint_violations_in_source('X = ".hq/config/experiments/state.json"\n')
    assert len(v) == 1 and v[0][1] == ".hq/config/experiments/state.json"
