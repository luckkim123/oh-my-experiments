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
