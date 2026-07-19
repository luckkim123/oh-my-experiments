"""Task 9 — tree-index generated INDEX.md (spec 2.6)."""
import json

from omx_core.cli import main
from omx_core.tree_ops import INDEX_MARKER
from tree_fixtures import GROUPED_TREE_YAML, build_grouped_tree


def _setup(tmp_path):
    fx = build_grouped_tree(tmp_path)
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "tree.yaml").write_text(GROUPED_TREE_YAML, encoding="utf-8")
    return fx


def test_index_written_newest_first_with_marker(tmp_path, capsys):
    _setup(tmp_path)
    assert main(["tree-index", "--root", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "written" and out["runs"] == 2
    text = (tmp_path / "experiments" / "INDEX.md").read_text()
    assert text.startswith(INDEX_MARKER)
    rows = [ln for ln in text.splitlines() if ln.startswith("| alpha_")]
    assert rows[0].startswith("| alpha_tune2_")     # newest first
    assert "latest" in rows[0]                       # alias mark on the target


def test_check_fresh_then_stale(tmp_path, capsys):
    _setup(tmp_path)
    assert main(["tree-index", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["tree-index", "--root", str(tmp_path), "--check"]) == 0
    assert json.loads(capsys.readouterr().out)["stale"] is False
    # grow the tree -> stale
    import json as _json
    new = tmp_path / "experiments" / "fw" / "exp_a" / "camp_a" / "alpha_tune3_260603_120000"
    new.mkdir(parents=True)
    (new / "manifest.json").write_text(_json.dumps({"run_id": new.name}))
    assert main(["tree-index", "--root", str(tmp_path), "--check"]) == 2


def test_marker_guard_precedes_check_and_adopt_overrides(tmp_path, capsys):
    _setup(tmp_path)
    handwritten = tmp_path / "experiments" / "INDEX.md"
    handwritten.write_text("# my hand-curated index\n")
    assert main(["tree-index", "--root", str(tmp_path), "--check"]) == 2
    assert "--adopt" in capsys.readouterr().err       # marker rc2, NOT a stale diff
    assert main(["tree-index", "--root", str(tmp_path), "--adopt"]) == 0
    assert INDEX_MARKER in handwritten.read_text()
