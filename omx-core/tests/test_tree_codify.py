"""Task 5 — tree-codify census inference (spec 2.2)."""
import json

from omx_core.cli import main
from omx_core.omx_paths import OmxPaths
from omx_core.tree import load_tree_schema
from tree_fixtures import build_grouped_tree


def test_codify_ignores_nested_manifest_under_a_run(tmp_path, capsys):
    """A run's own analysis dir may carry a nested manifest.json (e.g. an
    exp-analyze diagnose report) — codify must not miscount it as a deeper
    run and inflate the level census (final-review MUST-FIX F1)."""
    built = build_grouped_tree(tmp_path)
    run = built["runs"][0]
    (run / "analysis" / "diagnose-260601_130000").mkdir(parents=True)
    (run / "analysis" / "diagnose-260601_130000" / "manifest.json").write_text("{}")
    rc = main(["tree-codify", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    rep = out["report"]
    # Same census as the unpolluted grouped tree: 2 runs at levels 1..3, not
    # a deeper level4/level5 inflated by the nested manifest.json.
    assert rep["levels"]["value"] == ["level1", "level2", "level3"]
    assert rep["levels"]["sampled"] == 2
    schema = load_tree_schema(OmxPaths(root=tmp_path).tree_yaml())
    assert [n for n, _ in schema.trees["index"].levels] == ["level1", "level2", "level3"]


def test_codify_flags_uninferred_data_levels(tmp_path, capsys):
    """When codify infers a data root but cannot infer its levels (single-branch
    ambiguity), it must surface a data_levels report hint and a tree.yaml
    review-comment rather than silently shipping levels: [] (F2)."""
    build_grouped_tree(tmp_path)
    rc = main(["tree-codify", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    rep = out["report"]
    assert "data_root" in rep and rep["data_root"]["value"]
    assert rep["data_levels"] == {"value": [], "matched": 0, "sampled": rep["data_root"]["sampled"],
                                  "note": "not inferred — fill trees.data.levels "
                                          "before relying on tree-audit against "
                                          "the data tree (see tree.yaml comment)"}
    tree_yaml_text = OmxPaths(root=tmp_path).tree_yaml().read_text(encoding="utf-8")
    assert "levels not inferred" in tree_yaml_text


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
