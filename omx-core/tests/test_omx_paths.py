"""Unit tests for omx_paths — the OMX path single-source-of-truth.

Claude-free, Isaac-free, profile-free. Pure stdlib + pytest.
"""
from omx_core.omx_paths import OmxPathError


def test_error_type_is_valueerror_subclass():
    assert issubclass(OmxPathError, ValueError)


import pytest
from omx_core.omx_paths import (
    Profile, OmxPathError,
    validate_analysis_id, validate_session_id, validate_run_id, validate_token,
)


@pytest.mark.parametrize("good", ["20260530-143022-compare", "20260101-000000-next"])
def test_analysis_id_accepts_timestamped(good):
    validate_analysis_id(good)  # must not raise


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
from pathlib import Path
from omx_core.omx_paths import OmxPaths


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
    assert cp == p.run_dir("r13_teacher") / "cache" / "wandb__ss_error.parquet"


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
    assert p.registry_index() == p.omx_dir / "registry" / "INDEX.md"
    assert p.finding("doraemon_kl") == p.omx_dir / "registry" / "findings" / "doraemon_kl.md"
    assert p.state_json() == p.omx_dir / "state.json"


def test_finding_slug_validated(tmp_path):
    p = _paths(tmp_path)
    with pytest.raises(OmxPathError):
        p.finding("Bad Slug")


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
    assert p.cache_path("r1", source="wandb", metric="ss_error").name == "wandb__ss_error.parquet"
    with pytest.raises(OmxPathError):
        p.cache_path("r1", source="wandb", metric="attitude")  # not in profile.metrics


def test_empty_vocab_means_no_restriction(tmp_path):
    # Profile with metrics restricted but sources left empty: source is unrestricted,
    # metric is restricted (design: empty vocab set == no restriction for that field).
    prof = Profile(metrics={"ss_error"})  # sources defaults to empty frozenset
    p = OmxPaths(root=tmp_path, profile=prof)
    # arbitrary (structurally-valid) source passes because sources vocab is empty
    assert p.cache_path("r1", source="anything", metric="ss_error").name == "anything__ss_error.parquet"
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
        p.finding(evil)


# =============================================================================
# Task 4: permanent output-tree getters (output_root passed per-getter)
# =============================================================================
def test_analysis_tree(tmp_path):
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    a = p.analysis_dir(out, "r13_teacher", "20260530-143022-compare")
    assert a == out / "r13_teacher" / "analysis" / "20260530-143022-compare"
    assert p.report_md(out, "r13_teacher", "20260530-143022-compare") == a / "report.md"
    assert p.manifest_json(out, "r13_teacher", "20260530-143022-compare") == a / "manifest.json"


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
from omx_core.omx_paths import resolve_session_id, atomic_path, atomic_dir


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
def test_every_public_path_getter_is_exercised(tmp_path):
    """Guard: enumerate OmxPaths path-returning methods; ensure each is callable
    with a minimal valid arg set and returns a Path. Fails if a getter is added
    later without being added here (and given its own dedicated test above)."""
    p = _paths(tmp_path)
    out = tmp_path / "experiments"
    rid, aid, pid, sid = "r1", "20260530-143022-x", "20260530-143022-next", "s-1"
    calls = {
        "profile_file": lambda: p.profile_file("metrics.yaml"),
        "run_dir": lambda: p.run_dir(rid),
        "results_tsv": lambda: p.results_tsv(rid),
        "ledger_json": lambda: p.ledger_json(rid),
        "decision_log": lambda: p.decision_log(rid),
        "cache_path": lambda: p.cache_path(rid, source="wandb", metric="ss_error"),
        "scratch_dir": lambda: p.scratch_dir(session_id=sid),
        "scratch_plots": lambda: p.scratch_plots(session_id=sid),
        "scratch_py": lambda: p.scratch_py(session_id=sid),
        "scratch_notes": lambda: p.scratch_notes(session_id=sid),
        "registry_index": lambda: p.registry_index(),
        "finding": lambda: p.finding("slug1"),
        "state_json": lambda: p.state_json(),
        "analysis_dir": lambda: p.analysis_dir(out, rid, aid),
        "report_md": lambda: p.report_md(out, rid, aid),
        "manifest_json": lambda: p.manifest_json(out, rid, aid),
        "analysis_plot": lambda: p.analysis_plot(out, rid, aid, metric="m", view="v"),
        "analysis_table": lambda: p.analysis_table(out, rid, aid, metric="m", agg="a"),
        "proposal_md": lambda: p.proposal_md(out, rid, pid),
    }
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
