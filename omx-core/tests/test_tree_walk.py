"""Task 2 — generic walker + the spec 2.1 three-clause detection predicate."""
from omx_core.tree import runs_at_declared_depth, walk_runs, walk_symlinks
from tree_fixtures import build_flat_tree, build_grouped_tree


def test_grouped_tree_finds_both_runs_and_skips_noise(tmp_path):
    fx = build_grouped_tree(tmp_path)
    entries = walk_runs(fx["schema"], tmp_path)
    index_runs = runs_at_declared_depth(entries)
    leaves = sorted(e["leaf"] for e in index_runs)
    assert leaves == ["alpha_tune1_260601_120000", "alpha_tune2_260602_120000"]
    # legacy/ and _backup/ never surface; the alias symlink is not a run
    assert all("legacy" not in str(e["path"]) and "_backup" not in str(e["path"])
               for e in entries)


def test_detection_via_requires_and_grammar(tmp_path):
    fx = build_flat_tree(tmp_path)
    entries = runs_at_declared_depth(walk_runs(fx["schema"], tmp_path))
    via = {e["leaf"]: e["detected_via"] for e in entries}
    assert via["alpha_260601_120000"] == "requires"      # manifest present
    assert via["alpha_260602_120000"] == "grammar"       # clause (c): no manifest


def test_optional_level_omitted_is_declared_depth(tmp_path):
    fx = build_grouped_tree(tmp_path)
    # a run directly under exp (camp? omitted) is still at a declared depth
    import json
    run = tmp_path / "experiments" / "fw" / "exp_a" / "alpha_nocamp_260603_120000"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({"run_id": run.name}))
    entries = runs_at_declared_depth(walk_runs(fx["schema"], tmp_path))
    assert any(e["leaf"] == run.name for e in entries)


def test_wrong_depth_run_flagged_not_adopted(tmp_path):
    fx = build_grouped_tree(tmp_path)
    import json
    shallow = tmp_path / "experiments" / "alpha_shallow_260604_120000"
    shallow.mkdir(parents=True)
    (shallow / "manifest.json").write_text(json.dumps({"run_id": shallow.name}))
    entries = walk_runs(fx["schema"], tmp_path)
    hit = [e for e in entries if e["leaf"] == shallow.name]
    assert hit and hit[0]["at_declared_depth"] is False
    assert hit[0] not in runs_at_declared_depth(entries)


def test_data_tree_leaves_enumerated(tmp_path):
    fx = build_grouped_tree(tmp_path)
    data = [e for e in walk_runs(fx["schema"], tmp_path) if e["role"] == "data"]
    assert sorted(e["leaf"] for e in data) == ["260601_120000_tune1", "260602_120000_tune2"]
    assert all(e["detected_via"] == "depth" for e in data)


def test_walk_symlinks_reports_alias_and_train(tmp_path):
    fx = build_grouped_tree(tmp_path)
    links = walk_symlinks(fx["schema"], tmp_path)
    names = sorted(link["name"] for link in links)
    assert names == ["latest", "train", "train"]
    latest = next(link for link in links if link["name"] == "latest")
    assert latest["target"] is not None and latest["target"].name == "alpha_tune2_260602_120000"
