import json
from omx_core.cli import main


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
