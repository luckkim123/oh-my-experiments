import json
from omx_core.cli import main


def _strict_json_loads(raw):
    """Parse like a strict consumer (JS JSON.parse / jq): reject bare
    NaN/Infinity value tokens. Python's default json.loads accepts them, which
    would hide the very defect under test.

    parse_constant is the long-standing (and still-supported through 3.12) hook
    that fires on those exact tokens; chosen over a substring search because the
    echoed command legitimately lands in out["stdout"] as a JSON string that may
    contain the text "NaN" — only a bare *value* token is invalid."""
    def _reject(token):
        raise AssertionError(f"non-strict JSON token in output: {token}")
    return json.loads(raw, parse_constant=_reject)


def test_ingest_eval_summary_prints_counts(fixtures_dir, capsys):
    rc = main(["ingest", "--path", str(fixtures_dir / "summary.json"),
               "--format", "eval_summary"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["format"] == "eval_summary"
    assert out["n_summary"] == 70
    assert out["n_series"] == 0


def test_ingest_csv(fixtures_dir, capsys):
    rc = main(["ingest", "--path", str(fixtures_dir / "metrics_long.csv"),
               "--format", "csv_longform"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_summary"] == 4


def test_ingest_unknown_format_errors(fixtures_dir, capsys):
    rc = main(["ingest", "--path", str(fixtures_dir / "summary.json"),
               "--format", "nope"])
    assert rc != 0


def test_reduce_summarize_cv(fixtures_dir, capsys):
    rc = main(["reduce", "summarize", "--path", str(fixtures_dir / "summary.json"),
               "--format", "eval_summary", "--cv-field", "ss_error"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    rows = {(r["dr_level"], r["axis"]): r["cv"] for r in out["cv"]}
    assert ("none", "roll") in rows
    assert abs(rows[("none", "roll")] - 0.48 / 0.76) < 1e-6


def test_session_id_precedence_flag_wins(monkeypatch, capsys):
    monkeypatch.setenv("OMX_SESSION_ID", "from-env")
    rc = main(["session-id", "--session-id", "from-flag"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "from-flag"


def test_session_id_env_fallback(monkeypatch, capsys):
    monkeypatch.setenv("OMX_SESSION_ID", "from-env")
    rc = main(["session-id"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "from-env"


def test_reduce_summarize_nan_becomes_null(tmp_path, capsys):
    # a zero-mean axis -> CV = 0/0 = nan -> must serialize as JSON null, not NaN
    csv = tmp_path / "zero.csv"
    csv.write_text(
        "dr_level,axis,field,value\n"
        "none,vx,ss_error,0.0\n"
        "none,vx,ss_error_std,0.0\n"
    )
    rc = main(["reduce", "summarize", "--path", str(csv),
               "--format", "csv_longform", "--cv-field", "ss_error"])
    assert rc == 0
    raw = capsys.readouterr().out
    assert "NaN" not in raw                      # no invalid JSON token
    out = json.loads(raw)                        # strict parse must succeed
    assert out["cv"][0]["cv"] is None            # nan -> null


def test_eval_reference_prints_contract_json(capsys):
    rc = main(["eval", "--command", "echo '{\"pass\": true, \"score\": 0.8}'"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pass"
    assert out["pass"] is True
    assert out["score"] == 0.8


def test_eval_fail_verdict_is_rc0(capsys):
    # a graded FAIL is a successful eval (the evaluator worked) -> rc 0
    rc = main(["eval", "--command", "echo '{\"pass\": false}'"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "fail"


def test_eval_evaluator_error_is_rc1(capsys):
    # evaluator itself broke (unparseable) -> rc 1 so Bash can distinguish
    rc = main(["eval", "--command", "echo not-json"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "error"
    assert "parse_error" in out


def test_eval_nonzero_exit_is_rc1(capsys):
    rc = main(["eval", "--command", "exit 3"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "error"


def test_eval_with_decision_pass_only_keeps(capsys):
    rc = main(["eval", "--command", "echo '{\"pass\": true}'", "--keep-policy", "pass_only"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"]["decision"] == "keep"


def test_eval_b5_scoreless_under_score_improvement_is_ambiguous(capsys):
    # B5 coupling end-to-end: score-less pass under score_improvement -> ambiguous
    rc = main(["eval", "--command", "echo '{\"pass\": true}'", "--keep-policy", "score_improvement"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"]["decision"] == "ambiguous"


def test_eval_b5_scoreless_under_pass_only_keeps(capsys):
    # ...the SAME score-less candidate keeps under pass_only (the coupling's other half)
    rc = main(["eval", "--command", "echo '{\"pass\": true}'", "--keep-policy", "pass_only"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"]["decision"] == "keep"


def test_eval_score_improvement_with_score_keeps(capsys):
    rc = main(["eval", "--command", "echo '{\"pass\": true, \"score\": 0.9}'",
               "--keep-policy", "score_improvement", "--last-kept-score", "0.5"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"]["decision"] == "keep"


def test_eval_nonfinite_score_serializes_as_null(capsys):
    # an evaluator emitting a non-finite score (NaN) must not leak a bare NaN
    # *value* token into stdout — sibling _cmd_reduce_summarize already guards
    # this; _cmd_eval must match (top-level out["score"]).
    # Note: the echoed command lands in out["stdout"] as a JSON *string*
    # containing "NaN" — that is valid JSON, so the real invariant is that a
    # strict (allow_nan=False) parse succeeds, not substring-absence.
    rc = main(["eval", "--command", "echo '{\"pass\": true, \"score\": NaN}'"])
    assert rc == 0
    raw = capsys.readouterr().out
    out = _strict_json_loads(raw)                # strict parse must succeed
    assert out["score"] is None                  # non-finite -> null


def test_eval_nonfinite_score_null_in_nested_decision(capsys):
    # the same non-finite score is copied into out["decision"]["evaluator"]
    # when --keep-policy is set; a top-level-only fix would still leak a bare
    # NaN value token there.
    rc = main(["eval", "--command", "echo '{\"pass\": true, \"score\": NaN}'",
               "--keep-policy", "score_improvement"])
    assert rc == 0
    raw = capsys.readouterr().out
    out = _strict_json_loads(raw)                 # strict parse must succeed
    assert out["score"] is None
    assert out["decision"]["evaluator"]["score"] is None


def test_eval_unknown_keep_policy_errors(capsys):
    rc = main(["eval", "--command", "echo '{\"pass\": true}'", "--keep-policy", "bogus"])
    assert rc != 0
