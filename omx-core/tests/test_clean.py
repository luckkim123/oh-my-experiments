"""Task 10 — omx clean: dry-run default, trash never rm, .omx-only (spec 2.7)."""
import json
import os

from omx_core.cli import main


def _build_omx(tmp_path):
    omx = tmp_path / ".omx"
    (omx / "profile").mkdir(parents=True)
    (omx / "profile" / "metrics.yaml").write_text("x: 1\n")
    (omx / "registry" / "findings").mkdir(parents=True)
    (omx / "campaigns" / "camp_a").mkdir(parents=True)
    (omx / "scratch" / "sess1" / "plots").mkdir(parents=True)
    (omx / "scratch" / "sess1" / "plots" / "p.png").write_bytes(b"x" * 10)
    (omx / "scratch" / "sess2").mkdir(parents=True)
    (omx / "runs" / "r1" / "cache").mkdir(parents=True)
    (omx / "runs" / "r1" / "ledger.json").write_text("{}")
    (omx / "state.json").write_text("{}")
    (tmp_path / "experiments" / "keepme").mkdir(parents=True)  # output tree: untouchable
    return omx


def test_dry_run_lists_without_touching(tmp_path, capsys):
    omx = _build_omx(tmp_path)
    assert main(["clean", "--root", str(tmp_path), "--scope", "session"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    swept = {e["path"] for e in out["sweep"]}
    assert str(omx / "scratch" / "sess1") in swept
    assert str(omx / "scratch" / "sess2") in swept
    assert (omx / "scratch" / "sess1" / "plots" / "p.png").exists()  # nothing moved


def test_apply_trashes_scratch_keeps_everything_else(tmp_path, capsys):
    omx = _build_omx(tmp_path)
    assert main(["clean", "--root", str(tmp_path), "--scope", "session", "--apply"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert not (omx / "scratch" / "sess1").exists()
    trash = omx / ".trash"
    moved = list(trash.rglob("p.png"))
    assert len(moved) == 1                               # recoverable, relpath preserved
    assert (omx / "profile" / "metrics.yaml").exists()
    assert (omx / "runs" / "r1" / "ledger.json").exists()
    assert (omx / "campaigns" / "camp_a").exists()
    assert (omx / "state.json").exists()
    assert (tmp_path / "experiments" / "keepme").exists()  # output tree untouched
    assert "moved" in out


def test_scope_run_sweeps_cache_only(tmp_path, capsys):
    omx = _build_omx(tmp_path)
    assert main(["clean", "--root", str(tmp_path), "--scope", "run", "--apply"]) == 0
    assert not (omx / "runs" / "r1" / "cache").exists()
    assert (omx / "runs" / "r1" / "ledger.json").exists()
    assert (omx / "scratch" / "sess1").exists()          # session scope untouched


def test_older_than_filters_by_mtime_and_requires_d_suffix(tmp_path, capsys):
    omx = _build_omx(tmp_path)
    old = omx / "scratch" / "sess1"
    past = old.stat().st_mtime - 10 * 86400
    os.utime(old, (past, past))
    assert main(["clean", "--root", str(tmp_path), "--scope", "session",
                 "--older-than", "7d"]) == 0
    out = json.loads(capsys.readouterr().out)
    swept = {e["path"] for e in out["sweep"]}
    assert str(old) in swept and str(omx / "scratch" / "sess2") not in swept
    assert main(["clean", "--root", str(tmp_path), "--scope", "session",
                 "--older-than", "7"]) == 2              # missing 'd' suffix


def test_purge_requires_double_flag(tmp_path, capsys):
    _build_omx(tmp_path)
    assert main(["clean", "--root", str(tmp_path), "--scope", "session", "--apply"]) == 0
    capsys.readouterr()
    assert main(["clean", "--root", str(tmp_path), "--purge-trash"]) == 2
    assert "--i-understand-permanent" in capsys.readouterr().err
    assert main(["clean", "--root", str(tmp_path), "--purge-trash",
                 "--i-understand-permanent"]) == 0
