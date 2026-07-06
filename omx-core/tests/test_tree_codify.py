"""Task 5 — tree-codify census inference (spec 2.2)."""
import json

from omx_core.cli import main
from omx_core.omx_paths import OmxPaths
from omx_core.tree import load_tree_schema

from tree_fixtures import build_grouped_tree


def test_codify_infers_grouped_shape(tmp_path, capsys):
    build_grouped_tree(tmp_path)
    rc = main(["tree-codify", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pending_approval"] is True
    rep = out["report"]
    assert rep["ts_format"] == {"value": "%y%m%d_%H%M%S", "matched": 2, "sampled": 2}
    assert rep["tag"]["value"] == "required"
    schema = load_tree_schema(OmxPaths(root=tmp_path).tree_yaml())
    assert schema.trees["index"].root == "experiments"
    assert [n for n, _ in schema.trees["index"].levels] == ["level1", "level2", "level3"]
    assert schema.links["train"].kind == "data_pointer" and schema.links["train"].required
    assert schema.links["latest"].kind == "alias" and schema.links["latest"].scope == "level3"
    assert schema.requires == ("manifest.json",)
    assert schema.eval_modes == ("static",)
    assert "data" in schema.trees            # inferred from the train pointer targets


def test_codify_zero_runs_rc2(tmp_path, capsys):
    (tmp_path / "experiments").mkdir()
    rc = main(["tree-codify", "--root", str(tmp_path)])
    assert rc == 2
    assert "no runs detected" in capsys.readouterr().err


def test_codify_missing_index_root_rc2(tmp_path, capsys):
    rc = main(["tree-codify", "--root", str(tmp_path)])
    assert rc == 2
    assert "--index-root" in capsys.readouterr().err


def test_codify_refuses_overwrite_without_force(tmp_path, capsys):
    build_grouped_tree(tmp_path)
    assert main(["tree-codify", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["tree-codify", "--root", str(tmp_path)]) == 2
    assert "--force" in capsys.readouterr().err
    assert main(["tree-codify", "--root", str(tmp_path), "--force"]) == 0
