"""Task 7 — tree-scaffold mint-time refusals (spec 2.4) + codify round-trip."""
import json

from omx_core.cli import main
from omx_core.omx_paths import OmxPaths
from omx_core.tree import load_tree_schema
from tree_fixtures import GROUPED_TREE_YAML, build_grouped_tree


def _install_schema(tmp_path):
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True, exist_ok=True)
    (prof / "tree.yaml").write_text(GROUPED_TREE_YAML, encoding="utf-8")


def test_scaffold_run_creates_skeleton(tmp_path, capsys):
    build_grouped_tree(tmp_path)
    _install_schema(tmp_path)
    data = tmp_path / "heavy" / "fw" / "exp_a" / "260605_120000_fresh"
    data.mkdir(parents=True)
    rc = main(["tree-scaffold", "--root", str(tmp_path),
               "--run-id", "alpha_fresh_260605_120000",
               "--under", "fw/exp_a/camp_a", "--data-dir", str(data)])
    assert rc == 0
    run = tmp_path / "experiments" / "fw" / "exp_a" / "camp_a" / "alpha_fresh_260605_120000"
    assert (run / "config").is_dir() and (run / "analysis").is_dir()
    assert (run / "train").is_symlink() and (run / "train").resolve() == data.resolve()


def test_scaffold_refuses_existing_leaf_f4(tmp_path, capsys):
    build_grouped_tree(tmp_path)
    _install_schema(tmp_path)
    args = ["tree-scaffold", "--root", str(tmp_path),
            "--run-id", "alpha_tune1_260601_120000", "--under", "fw/exp_a/camp_a"]
    assert main(args) == 2
    assert "already exists" in capsys.readouterr().err


def test_scaffold_refuses_missing_tag_f8(tmp_path, capsys):
    build_grouped_tree(tmp_path)
    _install_schema(tmp_path)
    rc = main(["tree-scaffold", "--root", str(tmp_path),
               "--run-id", "alpha_260605_120000", "--under", "fw/exp_a/camp_a"])
    assert rc == 2
    assert "tag" in capsys.readouterr().err


def test_scaffold_depth_range_enforced(tmp_path, capsys):
    build_grouped_tree(tmp_path)
    _install_schema(tmp_path)
    rc = main(["tree-scaffold", "--root", str(tmp_path),
               "--run-id", "alpha_x_260605_120000", "--under", "fw"])
    assert rc == 2
    assert "segment" in capsys.readouterr().err


def test_scaffold_eval_mode_first_then_mint_and_f4(tmp_path, capsys):
    build_grouped_tree(tmp_path)
    _install_schema(tmp_path)
    bad = main(["tree-scaffold", "--root", str(tmp_path),
                "--eval-for", "alpha_tune1_260601_120000", "--mode", "bogus"])
    assert bad == 2 and "eval_modes" in capsys.readouterr().err
    ok = main(["tree-scaffold", "--root", str(tmp_path),
               "--eval-for", "alpha_tune1_260601_120000", "--mode", "static",
               "--ts", "260605_130000"])
    assert ok == 0
    leaf = (tmp_path / "experiments" / "fw" / "exp_a" / "camp_a"
            / "alpha_tune1_260601_120000" / "eval" / "static_260605_130000")
    assert leaf.is_dir()
    again = main(["tree-scaffold", "--root", str(tmp_path),
                  "--eval-for", "alpha_tune1_260601_120000", "--mode", "static",
                  "--ts", "260605_130000"])
    assert again == 2   # same-second re-mint refused


def test_scaffold_then_codify_round_trip(tmp_path, capsys):
    """Spec 3: build a tree purely via scaffold, codify it back, assert the
    inferred schema is semantically equivalent on the census-visible axes."""
    _install_schema(tmp_path)
    (tmp_path / "experiments").mkdir()
    for i, (tag, ts) in enumerate([("tune1", "260601_120000"), ("tune2", "260602_120000"),
                                   ("tune3", "260603_120000")]):
        data = tmp_path / "heavy" / "fw" / "exp_a" / f"{ts}_{tag}"
        data.mkdir(parents=True)
        rc = main(["tree-scaffold", "--root", str(tmp_path),
                   "--run-id", f"alpha_{tag}_{ts}",
                   "--under", "fw/exp_a/camp_a", "--data-dir", str(data)])
        assert rc == 0
        run = (tmp_path / "experiments" / "fw" / "exp_a" / "camp_a" / f"alpha_{tag}_{ts}")
        (run / "manifest.json").write_text(json.dumps({"run_id": run.name}))
    original = load_tree_schema(tmp_path / ".omx" / "profile" / "tree.yaml")
    capsys.readouterr()
    assert main(["tree-codify", "--root", str(tmp_path), "--force"]) == 0
    inferred = load_tree_schema(OmxPaths(root=tmp_path).tree_yaml())  # codify overwrote it
    assert inferred.ts_format == "%y%m%d_%H%M%S"
    assert inferred.tag == "required"
    assert set(inferred.links) >= {"train"}
    assert inferred.trees["index"].max_levels == original.trees["index"].max_levels
