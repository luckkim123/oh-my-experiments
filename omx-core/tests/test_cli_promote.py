import json
from pathlib import Path

from omx_core.cli import main


def _png(p, body=b"\x89PNG\r\n\x1a\n0"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)
    return p


def test_cli_promote_moves_referenced(tmp_path, capsys):
    from omx_core.omx_paths import OmxPaths
    paths = OmxPaths(root=tmp_path)
    sp = paths.scratch_plots(session_id="20260530-101010-1")
    _png(sp / "ss_error__trajectory.png", b"KEEP")
    _png(sp / "unused__bar.png", b"DROP")
    rc = main([
        "promote-plots", "--root", str(tmp_path), "--session-id", "20260530-101010-1",
        "--output-root", str(tmp_path / "experiments"), "--run-id", "run1",
        "--analysis-id", "20260530-101010-compare",
        "--referenced", "ss_error__trajectory.png",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    dest = Path(out["promoted"][0])
    assert dest.read_bytes() == b"KEEP"
    assert dest.name == "ss_error__trajectory.png"
    assert "analysis" in str(dest) and "20260530-101010-compare" in str(dest)
    # unreferenced remains in scratch
    assert (sp / "unused__bar.png").exists()


def test_cli_promote_multiple_referenced(tmp_path, capsys):
    from omx_core.omx_paths import OmxPaths
    paths = OmxPaths(root=tmp_path)
    sp = paths.scratch_plots(session_id="20260530-101010-1")
    _png(sp / "a.png", b"A")
    _png(sp / "b.png", b"B")
    rc = main([
        "promote-plots", "--root", str(tmp_path), "--session-id", "20260530-101010-1",
        "--output-root", str(tmp_path / "experiments"), "--run-id", "run1",
        "--analysis-id", "20260530-101010-compare",
        "--referenced", "a.png", "--referenced", "b.png",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["promoted"]) == 2


def test_cli_promote_missing_loud_fails(tmp_path):
    from omx_core.omx_paths import OmxPaths
    paths = OmxPaths(root=tmp_path)
    paths.scratch_plots(session_id="20260530-101010-1").mkdir(parents=True)
    rc = main([
        "promote-plots", "--root", str(tmp_path), "--session-id", "20260530-101010-1",
        "--output-root", str(tmp_path / "experiments"), "--run-id", "run1",
        "--analysis-id", "20260530-101010-compare",
        "--referenced", "ghost.png",
    ])
    assert rc == 2
