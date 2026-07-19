import json

import pytest
from omx_core.ingest.eval_summary import EvalSummaryAdapter
from omx_core.ingest.tensorboard import MAX_INGEST_BYTES_DEFAULT, MAX_SCALARS_DEFAULT, TensorboardAdapter
from omx_core.omx_paths import OmxError


def test_defaults_exist():
    assert MAX_SCALARS_DEFAULT == 10_000
    assert MAX_INGEST_BYTES_DEFAULT == 1 << 30


def test_eval_summary_over_byte_limit_loud_fails(tmp_path):
    p = tmp_path / "summary.json"
    p.write_text(json.dumps({"none": {"survival_pct": 1.0}}))
    with pytest.raises(OmxError, match="exceeds"):
        EvalSummaryAdapter(max_bytes=4).ingest(p)


def test_eval_summary_under_limit_ok(tmp_path):
    p = tmp_path / "summary.json"
    p.write_text(json.dumps({"none": {"survival_pct": 1.0}}))
    res = EvalSummaryAdapter(max_bytes=10_000).ingest(p)
    assert res.summary[0].value == 1.0


def test_tb_over_byte_limit_loud_fails(tmp_path):
    ev = tmp_path / "events.out.tfevents.123"
    ev.write_bytes(b"x" * 64)
    with pytest.raises(OmxError, match="exceeds"):
        TensorboardAdapter(max_bytes=8).ingest(ev)


def test_cli_ingest_accepts_bounds_flags(tmp_path, capsys):
    from omx_core.cli import main
    p = tmp_path / "summary.json"
    p.write_text(json.dumps({"none": {"survival_pct": 1.0}}))
    rc = main(["ingest", "--path", str(p), "--format", "eval_summary",
               "--max-bytes", "10000", "--max-scalars", "500"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_summary"] == 1


def test_cli_ingest_byte_limit_rc2(tmp_path, capsys):
    from omx_core.cli import main
    p = tmp_path / "summary.json"
    p.write_text(json.dumps({"none": {"survival_pct": 1.0}}))
    rc = main(["ingest", "--path", str(p), "--format", "eval_summary",
               "--max-bytes", "4"])
    assert rc == 2
    assert "exceeds" in capsys.readouterr().err


def test_cli_reduce_summarize_byte_limit_rc2(tmp_path, capsys):
    from omx_core.cli import main
    p = tmp_path / "summary.json"
    p.write_text(json.dumps({"none": {"survival_pct": 1.0}}))
    rc = main(["reduce", "summarize", "--path", str(p), "--format", "eval_summary",
               "--max-bytes", "4"])
    assert rc == 2
    assert "exceeds" in capsys.readouterr().err


def test_cli_plot_byte_limit_rc2(fixtures_dir, tmp_path, capsys):
    from omx_core.cli import main
    ev = fixtures_dir / "tb" / "events.out.tfevents.synthetic"
    rc = main([
        "plot", "--root", str(tmp_path), "--session-id", "20260530-101010-1",
        "--path", str(ev), "--format", "tensorboard",
        "--series", "Track/att/roll_err_deg", "--metric", "attitude", "--view", "trajectory",
        "--max-bytes", "4",
    ])
    assert rc == 2
    assert "exceeds" in capsys.readouterr().err
