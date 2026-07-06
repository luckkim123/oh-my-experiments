"""Task 4 — tree.yaml getter, init emission, sync-profile projection."""
import json

from omx_core.cli import main
from omx_core.omx_paths import OmxPaths
from omx_core.tree import load_tree_schema


def test_tree_yaml_getter(tmp_path):
    p = OmxPaths(root=tmp_path)
    assert p.tree_yaml() == tmp_path / ".omx" / "profile" / "tree.yaml"


def test_init_emits_default_tree_yaml(tmp_path, capsys):
    rc = main(["init", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "tree.yaml" in out["written"]
    schema = load_tree_schema(tmp_path / ".omx" / "profile" / "tree.yaml")
    assert set(schema.trees) == {"index"}


def test_init_force_never_clobbers_tree_yaml(tmp_path, capsys):
    assert main(["init", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    fp = OmxPaths(root=tmp_path).tree_yaml()
    fp.write_text(fp.read_text().replace("tag: optional", "tag: required"))
    assert main(["init", "--root", str(tmp_path), "--force"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "tree.yaml" not in out["written"]
    assert "tag: required" in fp.read_text()   # codified content survived --force


def test_sync_profile_projects_tree_summary(tmp_path, capsys):
    assert main(["init", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["wiki", "sync-profile", "--root", str(tmp_path)]) == 0
    page = (tmp_path / ".omx" / "registry" / "findings" / "profile.md").read_text()
    assert "## tree schema" in page
    assert "index: experiments" in page


def test_sync_profile_stale_on_tree_yaml_change(tmp_path, capsys):
    import os
    assert main(["init", "--root", str(tmp_path)]) == 0
    assert main(["wiki", "sync-profile", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    fp = OmxPaths(root=tmp_path).tree_yaml()
    fp.write_text(fp.read_text() + "# touched\n")
    future = fp.stat().st_mtime + 5
    os.utime(fp, (future, future))
    assert main(["wiki", "sync-profile", "--root", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["action"] == "synced"
