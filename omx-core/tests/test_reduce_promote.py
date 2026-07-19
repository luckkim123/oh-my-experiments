import pytest
from omx_core.omx_paths import OmxError
from omx_core.reduce.promote import promote_plots


def _png(path, body=b"\x89PNG\r\n\x1a\n0"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def test_promotes_only_referenced(tmp_path):
    scratch = tmp_path / "scratch" / "plots"
    dest = tmp_path / "analysis" / "plots"
    _png(scratch / "ss_error__trajectory.png", b"REFA")
    _png(scratch / "attitude__overlay.png", b"REFB")
    _png(scratch / "unused__bar.png", b"NOPE")
    moved = promote_plots(scratch, dest, ["ss_error__trajectory.png", "attitude__overlay.png"])
    assert sorted(p.name for p in moved) == ["attitude__overlay.png", "ss_error__trajectory.png"]
    assert (dest / "ss_error__trajectory.png").read_bytes() == b"REFA"
    assert (dest / "attitude__overlay.png").exists()
    assert not (scratch / "ss_error__trajectory.png").exists()
    assert (scratch / "unused__bar.png").read_bytes() == b"NOPE"
    assert not (dest / "unused__bar.png").exists()


def test_missing_referenced_loud_fails(tmp_path):
    scratch = tmp_path / "scratch" / "plots"
    dest = tmp_path / "analysis" / "plots"
    _png(scratch / "real.png")
    with pytest.raises(OmxError, match="ghost.png"):
        promote_plots(scratch, dest, ["real.png", "ghost.png"])
    # loud-fail happens BEFORE any move (real.png not yet promoted)
    assert (scratch / "real.png").exists()
    assert not (dest / "real.png").exists()


def test_empty_referenced_promotes_nothing(tmp_path):
    scratch = tmp_path / "scratch" / "plots"
    dest = tmp_path / "analysis" / "plots"
    _png(scratch / "a.png")
    assert promote_plots(scratch, dest, []) == []
    assert not dest.exists() or not any(dest.iterdir())
