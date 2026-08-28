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


# --- .hq/ cutover (Rule B): clean.py NEVER reaches into legacy once anchored --

def test_anchored_project_never_sweeps_legacy(tmp_path, capsys):
    """store-spec §7: the legacy store is not touched by anything but a
    separate purge during the fallback window. An anchored clean --apply must
    operate on the (empty) new .hq/ tree only, leaving every legacy-only
    scratch/run/tmp entry untouched — the opposite of list_campaigns()/
    list_programs(), which DO union both stores (Rule A)."""
    omx = _build_omx(tmp_path)
    anchor = tmp_path / ".hq" / ".anchor"
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("id: test-anchor\n", encoding="utf-8")
    assert main(["clean", "--root", str(tmp_path), "--scope", "all", "--apply"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["moved"] == []  # nothing under the (empty) new .hq/ tree to sweep
    assert (omx / "scratch" / "sess1" / "plots" / "p.png").exists()
    assert (omx / "scratch" / "sess2").exists()
    assert (omx / "runs" / "r1" / "cache").exists()
    assert not (omx / ".trash").exists()  # trash landed under .hq/, not .omx/


def test_anchored_project_sweeps_new_store_content(tmp_path, capsys):
    """The flip side: content that DOES live under the new .hq/ tree is still
    swept normally once anchored — Rule B is about never touching legacy, not
    about clean going inert."""
    anchor = tmp_path / ".hq" / ".anchor"
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("id: test-anchor\n", encoding="utf-8")
    scratch = tmp_path / ".hq" / "runtime" / "experiments" / "scratch" / "sess1"
    scratch.mkdir(parents=True)
    assert main(["clean", "--root", str(tmp_path), "--scope", "session", "--apply"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert not scratch.exists()
    # no leading dot on the new trash_root() -- runtime/ is already
    # .gitignore'd wholesale (team-lead trash-locus decision)
    trash = tmp_path / ".hq" / "runtime" / "experiments" / "trash"
    assert list(trash.rglob("sess1"))
    assert out["moved"]


def test_trash_locus_follows_the_resolved_store(tmp_path, capsys):
    """team-lead directive: a swept file lands under
    .hq/runtime/experiments/trash/ on an anchored project, and NOT under
    .omx/.trash — the exact failure a trash_root() that stayed pinned to
    .omx/ unconditionally would produce (a clean after --purge silently
    recreating .omx/.trash and undoing the purge). On an un-anchored project
    it still lands at .omx/.trash exactly as before this port."""
    anchor = tmp_path / ".hq" / ".anchor"
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("id: test-anchor\n", encoding="utf-8")
    scratch = tmp_path / ".hq" / "runtime" / "experiments" / "scratch" / "sess1"
    scratch.mkdir(parents=True)
    assert main(["clean", "--root", str(tmp_path), "--scope", "session", "--apply"]) == 0
    assert list((tmp_path / ".hq" / "runtime" / "experiments" / "trash").rglob("sess1"))
    assert not (tmp_path / ".omx").exists()  # never touched, let alone recreated


def test_trash_locus_unanchored_matches_pre_port_behavior(tmp_path, capsys):
    omx = _build_omx(tmp_path)
    assert main(["clean", "--root", str(tmp_path), "--scope", "session", "--apply"]) == 0
    assert list((omx / ".trash").rglob("p.png"))
    assert not (tmp_path / ".hq").exists()
