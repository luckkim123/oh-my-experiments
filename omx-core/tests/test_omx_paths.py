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
