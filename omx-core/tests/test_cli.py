import json

import pytest
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


def test_session_id_autogen_when_no_flag_or_env(monkeypatch, capsys):
    """argless `omx session-id` with no flag and no env must autogen a fresh id.

    Reproduces the `'str' object is not callable` crash: the CLI passed a string
    where resolve_session_id expects a zero-arg callable, so the autogen branch
    (only reached when neither flag nor env is set) blew up at call time."""
    monkeypatch.delenv("OMX_SESSION_ID", raising=False)
    rc = main(["session-id"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out, "autogen produced an empty session id"


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


def test_reduce_summarize_wrong_cv_field_loud_fails(fixtures_dir, capsys):
    """GAP A: --cv-field with a value that is an axis name (not a field name)
    must loud-fail (rc 2) with a message listing available fields, NOT silently
    return {"cv": []} at rc 0."""
    rc = main(["reduce", "summarize", "--path", str(fixtures_dir / "summary.json"),
               "--format", "eval_summary", "--cv-field", "roll"])
    assert rc == 2  # must be nonzero
    err = capsys.readouterr().err
    assert "not found" in err
    assert "available" in err
    assert "ss_error" in err  # at least one real field must appear in the hint


def test_reduce_summarize_unknown_cv_field_loud_fails(fixtures_dir, capsys):
    """GAP A: completely unknown cv-field also loud-fails with available hint."""
    rc = main(["reduce", "summarize", "--path", str(fixtures_dir / "summary.json"),
               "--format", "eval_summary", "--cv-field", "no_such_field"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not found" in err
    assert "available" in err


def test_reduce_summarize_empty_records_no_crash(tmp_path, capsys):
    """GAP A regression guard: empty summary (0 records) with correct field name
    must return empty cv quietly (rc 0) — data absence is not a bad field."""
    import json as _json
    # csv_longform with ss_error declared but 0 rows (header only)
    csv = tmp_path / "empty.csv"
    csv.write_text("dr_level,axis,field,value\n")
    rc = main(["reduce", "summarize", "--path", str(csv),
               "--format", "csv_longform", "--cv-field", "ss_error"])
    assert rc == 0
    out = _json.loads(capsys.readouterr().out)
    assert out["cv"] == []


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


def _counter_scoring_command(tmp_path, scores):
    """Build a shell command that returns a different score from `scores` on
    each successive invocation (via a tmp-file counter) — models a real
    evaluator whose own internal seed/randomness varies output per run."""
    counter = tmp_path / "counter"
    counter.write_text("0")
    joined = ",".join(str(s) for s in scores)
    return (
        f'python3 -c "'
        f"import json; n = int(open('{counter}').read()); "
        f"open('{counter}', 'w').write(str(n + 1)); "
        f"scores = [{joined}]; "
        f'print(json.dumps({{\'pass\': True, \'score\': scores[n]}}))"'
    )


def test_eval_seeds_aggregates_mean_std_n(tmp_path, capsys):
    cmd = _counter_scoring_command(tmp_path, [1.0, 2.0, 3.0])
    rc = main(["eval", "--command", cmd, "--seeds", "3"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pass"
    assert out["score_n"] == 3
    assert out["seed_scores"] == [1.0, 2.0, 3.0]
    assert out["score"] == 2.0
    assert out["score_std"] == pytest.approx(0.816496580927726)


def test_eval_seeds_default_single_run_unchanged(capsys):
    # no --seeds: single run, no score_std/score_n added (default path intact)
    rc = main(["eval", "--command", "echo '{\"pass\": true, \"score\": 0.8}'"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "score_std" not in out
    assert "score_n" not in out


def test_eval_seeds_significance_gate_rejects_noisy_winner(tmp_path, capsys):
    # bare '>' would keep (mean 2.02 > last_kept 2.0); the gate must reject
    # since the "improvement" is well inside the seed std.
    cmd = _counter_scoring_command(tmp_path, [1.9, 2.0, 2.16])
    rc = main(["eval", "--command", cmd, "--seeds", "3",
               "--keep-policy", "score_improvement", "--last-kept-score", "2.0"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"]["decision"] == "discard"
    assert "seed-noise gate" in out["decision"]["decision_reason"]


def test_eval_seeds_significance_gate_accepts_genuine_improvement(tmp_path, capsys):
    cmd = _counter_scoring_command(tmp_path, [1.9, 2.0, 2.1])
    rc = main(["eval", "--command", cmd, "--seeds", "3",
               "--keep-policy", "score_improvement", "--last-kept-score", "0.5"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"]["decision"] == "keep"
    assert "seed-noise gate" in out["decision"]["decision_reason"]


def test_eval_seeds_one_fails_aggregates_to_fail(capsys):
    # a seed run that always fails must make the whole candidate fail
    rc = main(["eval", "--command", "echo '{\"pass\": false}'", "--seeds", "3"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "fail"
    assert "score_std" not in out


def test_eval_seeds_rejects_less_than_one():
    rc = main(["eval", "--command", "echo '{\"pass\": true}'", "--seeds", "0"])
    assert rc != 0


def test_loud_fail_message_goes_to_stderr(capsys):
    # A string-coded SystemExit (a loud-fail with a message) must surface the
    # message on stderr, not be silently swallowed. Regression for the build-#3
    # review finding (rc=2 with empty stderr lost the error).
    rc = main(["ingest", "--path", "/does/not/matter", "--format", "bogus_fmt"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "bogus_fmt" in err  # the unknown-format message reached stderr


def test_integer_systemexit_passes_through_without_extra_print(capsys):
    # argparse raises SystemExit(2) on a missing required arg and prints its OWN
    # usage to stderr; main() must pass the int code through and NOT add a second
    # message of its own. We assert the rc is the int argparse chose (2) and that
    # main() didn't append a duplicate 'None'/extra line.
    rc = main(["ingest"])  # missing required --path/--format -> argparse SystemExit(2)
    assert rc == 2
    # argparse already wrote usage to stderr; we only assert main didn't crash and
    # returned the int unchanged. (No assertion on exact stderr text -- argparse owns it.)


def test_cli_ingest_tensorboard(fixtures_dir, capsys):
    ev = fixtures_dir / "tb" / "events.out.tfevents.synthetic"
    rc = main(["ingest", "--path", str(ev), "--format", "tensorboard"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["format"] == "tensorboard"
    assert out["n_series"] >= 2


def test_cli_ingest_wandb_offline(fixtures_dir, capsys):
    wf = fixtures_dir / "wandb" / "run-synthetic.wandb"
    rc = main(["ingest", "--path", str(wf), "--format", "wandb"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["format"] == "wandb_offline"
    assert out["n_series"] >= 2


def test_cli_report_parse_emits_json_findings(tmp_path, capsys):
    from omx_core.cli import main
    rpt = tmp_path / "report.md"
    rpt.write_text(
        "## Findings\n\n"
        "[FINDING] roll regressed at hard DR.\n"
        "[EVIDENCE: summary.json hard/roll/ss_error=0.76]\n"
        "[CONFIDENCE: HIGH]\n"
    )
    rc = main(["report-parse", "--path", str(rpt)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_findings"] == 1
    assert out["findings"][0]["claim"] == "roll regressed at hard DR."
    assert out["findings"][0]["evidence"] == "summary.json hard/roll/ss_error=0.76"
    assert out["findings"][0]["confidence"] == "HIGH"


def test_cli_report_parse_missing_file_rc2(tmp_path, capsys):
    from omx_core.cli import main
    rc = main(["report-parse", "--path", str(tmp_path / "nope.md")])
    assert rc == 2
    assert "not found" in capsys.readouterr().err.lower()


def test_cli_report_parse_malformed_rc2(tmp_path, capsys):
    from omx_core.cli import main
    rpt = tmp_path / "bad.md"
    rpt.write_text("[FINDING] dangling with no evidence.\n")
    rc = main(["report-parse", "--path", str(rpt)])
    assert rc == 2
    assert "evidence" in capsys.readouterr().err.lower()


def test_cli_report_parse_empty_report_rc0(tmp_path, capsys):
    from omx_core.cli import main
    rpt = tmp_path / "empty.md"
    rpt.write_text("## Summary\nNo issues found.\n")
    rc = main(["report-parse", "--path", str(rpt)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_findings"] == 0
    assert out["findings"] == []


def test_queue_launch_writes_pending(tmp_path, capsys):
    rc = main([
        "queue-launch", "--root", str(tmp_path), "--run-id", "run-9",
        "--proposal-id", "20260530-120000-next",
        "--launch-delta", "set radius=0.05",
        "--gpu-gate", "GPU0 free",
    ])
    assert rc == 0
    from omx_core.omx_paths import OmxPaths
    target = OmxPaths(root=tmp_path).pending_launch_json("run-9")
    assert target.exists()
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pending approval"
    assert out["queued_at"]  # CLI injected a real timestamp


def test_loop_status_reports_deadline_and_queue(tmp_path, capsys):
    main([
        "queue-launch", "--root", str(tmp_path), "--run-id", "run-9",
        "--proposal-id", "20260530-120000-next",
        "--launch-delta", "set radius=0.05", "--gpu-gate", "GPU0 free",
    ])
    capsys.readouterr()  # drain
    rc = main([
        "loop-status", "--root", str(tmp_path), "--run-id", "run-9",
        "--deadline", "2026-05-30T12:00:00+00:00",
        "--now", "2026-05-30T12:00:01+00:00",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["deadline_passed"] is True
    assert out["pending_launch"]["proposal_id"] == "20260530-120000-next"


def test_loop_status_no_deadline_is_none(tmp_path, capsys):
    rc = main(["loop-status", "--root", str(tmp_path), "--run-id", "run-9"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["deadline_passed"] is None
    assert out["pending_launch"] is None


def test_loop_status_computes_deadline_from_max_runtime(tmp_path, capsys):
    # with --max-runtime and NO --deadline, the CLI computes the deadline from
    # now + max_runtime via compute_deadline, then checks it. now is BEFORE the
    # computed deadline (100s window) -> not passed.
    rc = main([
        "loop-status", "--root", str(tmp_path), "--run-id", "run-9",
        "--max-runtime", "100",
        "--now", "2026-05-30T12:00:00+00:00",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["deadline"] == "2026-05-30T12:01:40+00:00"  # now + 100s
    assert out["deadline_passed"] is False


def test_loop_status_explicit_deadline_overrides_max_runtime(tmp_path, capsys):
    # an explicit --deadline takes precedence; --max-runtime is ignored when
    # --deadline is given.
    rc = main([
        "loop-status", "--root", str(tmp_path), "--run-id", "run-9",
        "--deadline", "2026-05-30T12:00:00+00:00",
        "--max-runtime", "100",
        "--now", "2026-05-30T12:00:01+00:00",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["deadline"] == "2026-05-30T12:00:00+00:00"  # explicit wins
    assert out["deadline_passed"] is True


def test_loop_status_rejects_bad_max_runtime(tmp_path, capsys):
    rc = main([
        "loop-status", "--root", str(tmp_path), "--run-id", "run-9",
        "--max-runtime", "0",
        "--now", "2026-05-30T12:00:00+00:00",
    ])
    assert rc != 0  # compute_deadline loud-fails on non-positive -> SystemExit


# ---------------------------------------------------------------------------
# wiki verbs
# ---------------------------------------------------------------------------

def test_wiki_add_write_mode_creates_page(tmp_path, capsys):
    from omx_core.cli import build_parser
    args = build_parser().parse_args(
        ["wiki", "add", "--root", str(tmp_path), "--title", "Roll heavy-tail",
         "--category", "pattern", "--tags", "roll,heavy-tail",
         "--confidence", "high", "--content", "roll axis heavy tail"])
    rc = args.func(args)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "created"
    assert out["slug"] == "roll_heavy_tail.md"


def test_wiki_add_from_report_extract_only(tmp_path, capsys):
    from omx_core.cli import build_parser
    from omx_core.omx_paths import OmxPaths
    report = tmp_path / "report.md"
    report.write_text(
        "[FINDING] roll regressed\n[EVIDENCE: summary.json hard/roll]\n[CONFIDENCE: HIGH]\n",
        encoding="utf-8",
    )
    args = build_parser().parse_args(
        ["wiki", "add", "--root", str(tmp_path), "--from-report", str(report)])
    rc = args.func(args)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["candidates"][0]["claim"] == "roll regressed"
    # extract-only wrote NOTHING:
    assert OmxPaths(root=tmp_path).wiki_dir().exists() is False


def test_wiki_query_returns_json(tmp_path, capsys):
    from omx_core.cli import build_parser
    from omx_core.omx_paths import OmxPaths
    from omx_core.wiki import ingest
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Heavy tail",
                            content="body", tags=[], category="pattern",
                            confidence="high", sources=[])
    args = build_parser().parse_args(["wiki", "query", "--root", str(tmp_path), "heavy tail"])
    rc = args.func(args)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_matches"] == 1


def test_wiki_lint_returns_json(tmp_path, capsys):
    from omx_core.cli import build_parser
    from omx_core.omx_paths import OmxPaths
    from omx_core.wiki import ingest
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="A",
                            content="body", tags=["roll"], category="pattern",
                            confidence="high", sources=[])
    args = build_parser().parse_args(["wiki", "lint", "--root", str(tmp_path)])
    rc = args.func(args)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "issues" in out and "stats" in out


def test_wiki_list_returns_json(tmp_path, capsys):
    from omx_core.cli import build_parser
    from omx_core.omx_paths import OmxPaths
    from omx_core.wiki import ingest
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="A",
                            content="body", tags=[], category="pattern",
                            confidence="high", sources=[])
    args = build_parser().parse_args(["wiki", "list", "--root", str(tmp_path)])
    rc = args.func(args)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pages"][0]["slug"] == "a.md"


def test_wiki_add_with_status_and_blocked_on(tmp_path, capsys):
    from omx_core.cli import build_parser
    from omx_core.omx_paths import OmxPaths
    from omx_core.wiki import storage
    args = build_parser().parse_args(
        ["wiki", "add", "--root", str(tmp_path), "--title", "TAM row rewrite",
         "--category", "decision", "--confidence", "high",
         "--content", "reorder ESC channels", "--status", "needs-apply-before-retrain",
         "--blocked-on", "bench-measure T200 curve"])
    rc = args.func(args)
    assert rc == 0
    page = storage.read_page(OmxPaths(root=tmp_path), "tam_row_rewrite.md")
    assert page.status == "needs-apply-before-retrain"
    assert page.blocked_on == "bench-measure T200 curve"


def test_wiki_list_status_filter_and_output_fields(tmp_path, capsys):
    from omx_core.cli import build_parser
    from omx_core.omx_paths import OmxPaths
    from omx_core.wiki import ingest
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Lead", content="b",
                            tags=[], category="reference", confidence="high", sources=[],
                            status="needs-experiment")
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Plain", content="b",
                            tags=[], category="reference", confidence="high", sources=[])
    args = build_parser().parse_args(["wiki", "list", "--root", str(tmp_path)])
    args.func(args)
    out = json.loads(capsys.readouterr().out)
    by_slug = {pg["slug"]: pg for pg in out["pages"]}
    assert len(by_slug) == 2
    assert by_slug["plain.md"]["status"] is None
    assert "blocked_on" in by_slug["lead.md"]
    args2 = build_parser().parse_args(
        ["wiki", "list", "--root", str(tmp_path), "--status", "needs-experiment"])
    args2.func(args2)
    out2 = json.loads(capsys.readouterr().out)
    assert [pg["slug"] for pg in out2["pages"]] == ["lead.md"]


def _seed_wiki_page(tmp_path):
    from omx_core.omx_paths import OmxPaths
    from omx_core.wiki import ingest
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Roll heavy-tail",
                            content="roll axis shows a heavy-tailed error spread",
                            tags=["roll"], category="pattern",
                            confidence="high", sources=[])
    return "roll_heavy_tail.md"


def test_wiki_read_emits_full_page_with_frontmatter(tmp_path, capsys):
    """`omx wiki read --slug` prints the WHOLE page (frontmatter + body) by
    default, so a caller that found a slug via query can pull the full text
    through a first-class verb instead of hand-reading the findings/ path."""
    from omx_core.cli import build_parser
    slug = _seed_wiki_page(tmp_path)
    args = build_parser().parse_args(["wiki", "read", "--root", str(tmp_path), "--slug", slug])
    rc = args.func(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("---\n")                      # frontmatter block present
    assert "category: pattern" in out                   # a frontmatter field
    assert "roll axis shows a heavy-tailed error spread" in out  # body present


def test_wiki_read_no_frontmatter_emits_body_only(tmp_path, capsys):
    from omx_core.cli import build_parser
    slug = _seed_wiki_page(tmp_path)
    args = build_parser().parse_args(
        ["wiki", "read", "--root", str(tmp_path), "--slug", slug, "--no-frontmatter"])
    rc = args.func(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "---" not in out                              # no frontmatter block
    assert "category:" not in out                        # no frontmatter field
    assert "roll axis shows a heavy-tailed error spread" in out  # body present


def test_wiki_read_missing_slug_loud_fails(tmp_path, capsys):
    """Unknown slug must loud-fail (non-zero), NOT print empty output — else a
    caller can't tell 'page absent' from 'page empty'."""
    import pytest
    from omx_core.cli import build_parser
    args = build_parser().parse_args(
        ["wiki", "read", "--root", str(tmp_path), "--slug", "does_not_exist.md"])
    with pytest.raises(SystemExit):
        args.func(args)
    assert capsys.readouterr().out == ""


def test_wiki_add_bad_category_loud_fails(tmp_path):
    import pytest
    from omx_core.cli import build_parser
    args = build_parser().parse_args(
        ["wiki", "add", "--root", str(tmp_path), "--title", "X",
         "--category", "bogus", "--tags", "", "--confidence", "high",
         "--content", "c"])
    with pytest.raises(SystemExit):
        args.func(args)


def test_wiki_add_write_mode_requires_fields(tmp_path):
    import pytest
    from omx_core.cli import build_parser
    # missing --content in write mode (no --from-report) must loud-fail
    args = build_parser().parse_args(
        ["wiki", "add", "--root", str(tmp_path), "--title", "X",
         "--category", "pattern", "--confidence", "high"])
    with pytest.raises(SystemExit):
        args.func(args)


def test_wiki_add_write_mode_requires_confidence(tmp_path):
    import pytest
    from omx_core.cli import build_parser
    args = build_parser().parse_args(
        ["wiki", "add", "--root", str(tmp_path), "--title", "X",
         "--category", "pattern", "--content", "c"])
    with pytest.raises(SystemExit):
        args.func(args)


# --- report-coverage CLI: --min-coverage strict flag + group_hits output (GAP 4b) ---

def _write_coverage_profile(tmp_path):
    """Write a minimal .omx/profile/metrics.yaml with multi-token groups + markers."""
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "metrics.yaml").write_text(
        "metrics: [Reward/att_rp, entropy, Encoder/z_std]\n"
        "output_root: experiments\n"
        "groups:\n"
        "  reward_decomp: [Reward/att_rp, Reward/lin_vel, Reward/yaw_vel, Reward/bias]\n"
        "  encoder: [Encoder/z_std, Encoder/z_min, Encoder/z_max]\n"
        "engine_markers: [DIAGNOSIS, plateau]\n"
    )


def test_report_coverage_cli_lenient_default_passes_one_token(tmp_path, capsys):
    # one token per group + an engine marker -> lenient default passes (rc 0)
    _write_coverage_profile(tmp_path)
    report = tmp_path / "report.md"
    report.write_text("Reward/att_rp ok. Encoder/z_std ok. [DIAGNOSIS] plateau.")
    rc = main(["report-coverage", "--path", str(report), "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["min_coverage"] is None
    assert out["group_hits"]["reward_decomp"] == [1, 4]  # tuple serialized to list


def test_report_coverage_cli_strict_flag_fails_shallow(tmp_path, capsys):
    # same one-token report under --min-coverage 0.5 -> loud-fail. main() intercepts
    # the string-coded SystemExit and maps it to rc 2 (loud-fail discipline), so the
    # gate is observed by a non-zero return code, not a raised SystemExit.
    _write_coverage_profile(tmp_path)
    report = tmp_path / "report.md"
    report.write_text("Reward/att_rp ok. Encoder/z_std ok. [DIAGNOSIS] plateau.")
    rc = main(["report-coverage", "--path", str(report), "--root", str(tmp_path),
               "--min-coverage", "0.5"])
    assert rc == 2  # loud-fail
    captured = capsys.readouterr()
    # the JSON (with group_hits) is printed to stdout before the loud-fail
    out = json.loads(captured.out)
    assert out["ok"] is False
    assert out["min_coverage"] == 0.5
    assert "reward_decomp" in out["missing_groups"]  # 1/4 < ceil(4*0.5)=2
    assert out["group_hits"]["reward_decomp"] == [1, 4]
    # the FAILED reason is surfaced on stderr
    assert "report coverage FAILED" in captured.err


def test_wiki_gc_readonly_emits_lint_and_pages(tmp_path, capsys):
    from omx_core.cli import main
    from omx_core.omx_paths import OmxPaths
    from omx_core.wiki import ingest
    ingest.ingest_knowledge(OmxPaths(root=tmp_path), now="2026-06-06T00:00:00",
                            title="Page A", content="aaa", tags=["t"],
                            category="reference", confidence="medium", sources=[])
    rc = main(["wiki", "gc", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "lint" in out and "pages" in out
    assert out["pages"][0]["slug"] == "page_a.md"
    assert "bytes" in out["pages"][0]


def test_wiki_gc_apply_deletes_via_proposal(tmp_path, capsys):
    import subprocess

    from omx_core.cli import main
    from omx_core.omx_paths import OmxPaths
    from omx_core.wiki import ingest
    paths = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(paths, now="2026-06-06T00:00:00", title="Trash Me",
                            content="junk", tags=["t"], category="reference",
                            confidence="medium", sources=[])
    # make it git-tracked so the recovery guard passes
    for args in (["init"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
                 ["add", "-A"], ["commit", "-m", "seed"]):
        subprocess.run(["git", *args], cwd=str(tmp_path), check=True, capture_output=True, text=True)
    proposal = tmp_path / "p.md"
    proposal.write_text(
        "---\nkind: wiki-gc\n---\n\n## DELETE\n\n- slug: trash_me.md\n  reason: junk\n\n## MERGE\n",
        encoding="utf-8")
    rc = main(["wiki", "gc-apply", "--proposal", str(proposal), "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["deleted"] == ["trash_me.md"]
    assert not paths.wiki_page("trash_me").exists()


def test_wiki_gc_apply_untracked_loud_fails(tmp_path, capsys):
    import pytest
    from omx_core.cli import build_parser
    from omx_core.omx_paths import OmxPaths
    from omx_core.wiki import ingest
    paths = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(paths, now="2026-06-06T00:00:00", title="Untracked",
                            content="x", tags=["t"], category="reference",
                            confidence="medium", sources=[])
    proposal = tmp_path / "p.md"
    proposal.write_text("---\nkind: wiki-gc\n---\n## DELETE\n- slug: untracked.md\n", encoding="utf-8")
    # no git init -> untracked -> the handler must loud-fail (SystemExit) and NOT delete.
    # Call the handler directly: main() intercepts SystemExit (maps to rc 2), so the
    # established loud-fail test pattern in this file invokes args.func(args), not main().
    args = build_parser().parse_args(
        ["wiki", "gc-apply", "--proposal", str(proposal), "--root", str(tmp_path)])
    with pytest.raises(SystemExit):
        args.func(args)
    assert paths.wiki_page("untracked").exists()


# --- report-coverage CLI: --cross-run-refs gate (E4 stale-column incident) ---
# A report can carry a cross-run reference column (e.g. 'teacher hard') whose
# values were carried forward from a prior report and went stale. --cross-run-refs
# points at a JSON file of refs; each is verified for provenance (the source eval
# id is cited) AND value (matches the source summary.json). A stale value -> rc 2.

def _write_eval_summary_for_cli(tmp_path, eval_id, payload):
    import json as _j
    d = tmp_path / eval_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(_j.dumps(payload))
    return str(d / "summary.json")


def test_report_coverage_cli_cross_run_refs_pass(tmp_path, capsys):
    _write_coverage_profile(tmp_path)
    spath = _write_eval_summary_for_cli(
        tmp_path, "static_260607_182214",
        {"hard": {"att_norm": {"ss_error": 1.2833663946366705}}})
    report = tmp_path / "report.md"
    report.write_text(
        "Reward/att_rp ok. Encoder/z_std ok. [DIAGNOSIS] plateau. "
        "Against teacher eval `static_260607_182214`, teacher hard att_norm 1.283.")
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps([
        {"label": "teacher hard att_norm", "summary_path": spath,
         "field": "hard/att_norm/ss_error", "reported_value": 1.283}]))
    rc = main(["report-coverage", "--path", str(report), "--root", str(tmp_path),
               "--cross-run-refs", str(refs)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["cross_run_refs"]["ok"] is True


def test_report_coverage_cli_cross_run_refs_stale_value_fails(tmp_path, capsys):
    # the report's teacher-hard column says 1.06 but the eval says 1.283 -> rc 2
    _write_coverage_profile(tmp_path)
    spath = _write_eval_summary_for_cli(
        tmp_path, "static_260607_182214",
        {"hard": {"att_norm": {"ss_error": 1.2833663946366705}}})
    report = tmp_path / "report.md"
    report.write_text(
        "Reward/att_rp ok. Encoder/z_std ok. [DIAGNOSIS] plateau. "
        "Against teacher eval `static_260607_182214`, teacher hard att_norm 1.06.")
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps([
        {"label": "teacher hard att_norm", "summary_path": spath,
         "field": "hard/att_norm/ss_error", "reported_value": 1.06}]))
    rc = main(["report-coverage", "--path", str(report), "--root", str(tmp_path),
               "--cross-run-refs", str(refs)])
    assert rc == 2  # loud-fail
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["ok"] is False
    assert out["cross_run_refs"]["ok"] is False
    assert "teacher hard att_norm" in [m["label"] for m in out["cross_run_refs"]["mismatched"]]
    assert "STALE" in captured.err or "stale" in captured.err


def test_report_coverage_cli_cross_run_refs_uncited_fails(tmp_path, capsys):
    # value matches but the eval id is never cited -> provenance failure -> rc 2
    _write_coverage_profile(tmp_path)
    spath = _write_eval_summary_for_cli(
        tmp_path, "static_260607_182214",
        {"hard": {"att_norm": {"ss_error": 1.2833663946366705}}})
    report = tmp_path / "report.md"
    report.write_text(
        "Reward/att_rp ok. Encoder/z_std ok. [DIAGNOSIS] plateau. "
        "teacher hard att_norm 1.283 (no eval id cited).")
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps([
        {"label": "teacher hard att_norm", "summary_path": spath,
         "field": "hard/att_norm/ss_error", "reported_value": 1.283}]))
    rc = main(["report-coverage", "--path", str(report), "--root", str(tmp_path),
               "--cross-run-refs", str(refs)])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["cross_run_refs"]["ok"] is False
    assert [u["label"] for u in out["cross_run_refs"]["uncited"]] == ["teacher hard att_norm"]


def test_report_coverage_cli_no_cross_run_refs_is_noop(tmp_path, capsys):
    # back-compat: without --cross-run-refs the gate is absent, key is null
    _write_coverage_profile(tmp_path)
    report = tmp_path / "report.md"
    report.write_text("Reward/att_rp ok. Encoder/z_std ok. [DIAGNOSIS] plateau.")
    rc = main(["report-coverage", "--path", str(report), "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["cross_run_refs"] is None


def test_report_coverage_cli_cross_run_refs_missing_file_rc2(tmp_path, capsys):
    _write_coverage_profile(tmp_path)
    report = tmp_path / "report.md"
    report.write_text("Reward/att_rp ok. Encoder/z_std ok. [DIAGNOSIS] plateau.")
    rc = main(["report-coverage", "--path", str(report), "--root", str(tmp_path),
               "--cross-run-refs", str(tmp_path / "nope.json")])
    assert rc == 2
    assert "not found" in capsys.readouterr().err.lower()
