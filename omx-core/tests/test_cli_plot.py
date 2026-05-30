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
