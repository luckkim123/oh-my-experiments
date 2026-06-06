import json
from omx_core.cli import main


def _png_ok(path):
    return path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_cli_plot_line_from_tb_to_scratch(fixtures_dir, tmp_path, capsys):
    ev = fixtures_dir / "tb" / "events.out.tfevents.synthetic"
    rc = main([
        "plot", "--root", str(tmp_path), "--session-id", "20260530-101010-1",
        "--path", str(ev), "--format", "tensorboard",
        "--series", "Track/att/roll_err_deg", "--metric", "attitude", "--view", "trajectory",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    from pathlib import Path
    png = Path(out["plot"])
    assert png.name == "attitude__trajectory.png"
    assert "scratch" in str(png)
    assert _png_ok(png)


def test_cli_plot_unknown_series_loud_fails(fixtures_dir, tmp_path):
    ev = fixtures_dir / "tb" / "events.out.tfevents.synthetic"
    rc = main([
        "plot", "--root", str(tmp_path), "--session-id", "20260530-101010-1",
        "--path", str(ev), "--format", "tensorboard",
        "--series", "Nope/missing", "--metric", "attitude", "--view", "trajectory",
    ])
    assert rc == 2  # loud-fail via SystemExit -> rc 2


def test_cli_plot_bad_metric_token_fails(fixtures_dir, tmp_path):
    ev = fixtures_dir / "tb" / "events.out.tfevents.synthetic"
    rc = main([
        "plot", "--root", str(tmp_path), "--session-id", "20260530-101010-1",
        "--path", str(ev), "--format", "tensorboard",
        "--series", "Track/att/roll_err_deg",
        "--metric", "Bad__Token", "--view", "trajectory",
    ])
    assert rc == 2


def test_cli_plot_npz_1d_series(fixtures_dir, tmp_path, capsys):
    npz = fixtures_dir / "data_none.npz"
    rc = main([
        "plot", "--root", str(tmp_path), "--session-id", "20260530-101010-1",
        "--path", str(npz), "--format", "npz",
        "--series", "target_roll_deg", "--metric", "attitude", "--view", "trajectory",
    ])
    assert rc == 0
    import json
    out = json.loads(capsys.readouterr().out)
    from pathlib import Path
    assert Path(out["plot"]).name == "attitude__trajectory.png"


def test_cli_plot_npz_2d_series_gives_nd_hint(fixtures_dir, tmp_path, capsys):
    npz = fixtures_dir / "data_none.npz"
    rc = main([
        "plot", "--root", str(tmp_path), "--session-id", "20260530-101010-1",
        "--path", str(npz), "--format", "npz",
        "--series", "error_roll", "--metric", "attitude", "--view", "trajectory",
    ])
    assert rc == 2


def test_cli_plot_eval_summary_per_axis_bar_produces_png(fixtures_dir, tmp_path, capsys):
    """GAP B Option 1: omx plot --format eval_summary --view per_axis_bar must
    produce a real PNG for a known --series (field name like ss_error).
    Previously returned rc 2 because EvalSummaryAdapter.ingest() set series={}."""
    from pathlib import Path
    rc = main([
        "plot", "--root", str(tmp_path), "--session-id", "20260530-101010-1",
        "--path", str(fixtures_dir / "summary.json"), "--format", "eval_summary",
        "--series", "ss_error", "--metric", "ss_error", "--view", "per_axis_bar",
    ])
    assert rc == 0, "eval_summary per_axis_bar plot must succeed"
    out = json.loads(capsys.readouterr().out)
    png = Path(out["plot"])
    assert png.name == "ss_error__per_axis_bar.png"
    assert _png_ok(png), "output must be a valid PNG"


def test_cli_plot_eval_summary_unknown_field_loud_fails(fixtures_dir, tmp_path, capsys):
    """GAP B: unknown --series on eval_summary must loud-fail with available hint."""
    rc = main([
        "plot", "--root", str(tmp_path), "--session-id", "20260530-101010-1",
        "--path", str(fixtures_dir / "summary.json"), "--format", "eval_summary",
        "--series", "no_such_field", "--metric", "ss_error", "--view", "per_axis_bar",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "available" in err
