"""Task 8 — tree-alias declared-only aliases + atomic re-point (spec 2.5)."""
import json

from omx_core.cli import main

from tree_fixtures import GROUPED_TREE_YAML, build_grouped_tree


def _setup(tmp_path):
    fx = build_grouped_tree(tmp_path)
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "tree.yaml").write_text(GROUPED_TREE_YAML, encoding="utf-8")
    return fx


def test_repoint_latest_is_atomic_and_scope_derived(tmp_path, capsys):
    fx = _setup(tmp_path)
    camp = fx["camp"]
    assert (camp / "latest").resolve().name == "alpha_tune2_260602_120000"
    rc = main(["tree-alias", "--root", str(tmp_path),
               "--name", "latest", "--run", "alpha_tune1_260601_120000"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["scope_dir"].endswith("camp_a")          # derived from the run's ancestry
    assert (camp / "latest").resolve().name == "alpha_tune1_260601_120000"
    leftovers = [p.name for p in camp.iterdir() if p.name.startswith(".latest")]
    assert leftovers == []                               # no temp symlink left behind


def test_undeclared_alias_name_rc2(tmp_path, capsys):
    _setup(tmp_path)
    rc = main(["tree-alias", "--root", str(tmp_path),
               "--name", "best", "--run", "alpha_tune1_260601_120000"])
    assert rc == 2
    assert "declared" in capsys.readouterr().err


def test_missing_target_run_rc2(tmp_path, capsys):
    _setup(tmp_path)
    rc = main(["tree-alias", "--root", str(tmp_path),
               "--name", "latest", "--run", "alpha_nope_260609_120000"])
    assert rc == 2
    assert "no run named" in capsys.readouterr().err


def test_list_reports_alias_census(tmp_path, capsys):
    _setup(tmp_path)
    rc = main(["tree-alias", "--root", str(tmp_path), "--list"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert [a["name"] for a in out["aliases"]] == ["latest"]
    assert out["aliases"][0]["dangling"] is False
