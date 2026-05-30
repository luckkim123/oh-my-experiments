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
