"""Task 3 — the 5-stage .omx anchor resolution ladder (#13)."""
import subprocess

from omx_core.root import MARKER, project_id, resolve_omx_root


def test_explicit_always_wins(tmp_path):
    root, stage = resolve_omx_root(str(tmp_path), cwd=tmp_path / "sub", env={})
    assert (root, stage) == (tmp_path, "explicit")


def test_state_dir_uses_project_id(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    state = tmp_path / "state"
    root, stage = resolve_omx_root(None, cwd=proj, env={"OMX_STATE_DIR": str(state)})
    assert stage == "state-dir"
    assert root.parent == state
    assert root.name.startswith("proj-") and len(root.name) == len("proj-") + 16


def test_marker_climb_stops_before_home(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: tmp_path))
    ws = tmp_path / "ws"
    deep = ws / "a" / "b"
    deep.mkdir(parents=True)
    (ws / MARKER).touch()
    root, stage = resolve_omx_root(None, cwd=deep, env={})
    assert (root, stage) == (ws, "marker")
    # marker at $HOME itself is never honored
    (ws / MARKER).unlink()
    (tmp_path / MARKER).touch()
    root, stage = resolve_omx_root(None, cwd=deep, env={})
    assert stage != "marker"


def test_git_toplevel_stage(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: tmp_path.parent))
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    root, stage = resolve_omx_root(None, cwd=repo / "sub", env={})
    assert (root, stage) == (repo, "git")


def test_cwd_fallback_and_kill_switch(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: tmp_path.parent))
    plain = tmp_path / "plain"
    plain.mkdir()
    root, stage = resolve_omx_root(None, cwd=plain, env={})
    assert (root, stage) == (plain, "cwd")
    # kill switch collapses the ladder even when a marker exists above
    (tmp_path / MARKER).touch()
    root, stage = resolve_omx_root(None, cwd=plain, env={"OMX_NO_ROOT_LADDER": "1"})
    assert (root, stage) == (plain, "cwd")


def test_project_id_identity_prefers_remote(tmp_path):
    a = project_id(tmp_path / "x", "git@host:org/repo.git")
    b = project_id(tmp_path / "y", "git@host:org/repo.git")
    assert a.split("-")[-1] == b.split("-")[-1]      # same identity hash
    assert a.startswith("x-") and b.startswith("y-")  # placement basename differs


def test_no_required_root_left_anywhere():
    import argparse
    from omx_core.cli import build_parser

    def walk(parser):
        for a in parser._actions:
            if isinstance(a, argparse._SubParsersAction):
                for sp in a.choices.values():
                    walk(sp)
            elif "--root" in getattr(a, "option_strings", ()):
                assert not a.required, f"--root still required on {parser.prog}"

    walk(build_parser())
