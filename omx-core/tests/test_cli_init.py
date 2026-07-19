"""CLI-level tests for `omx init` (build #3 task 3)."""
import json

import yaml
from omx_core.cli import main
from omx_core.omx_paths import OmxPaths


def test_init_default_creates_profile(tmp_path, capsys):
    rc = main(["init", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["profile_name"] == "isaaclab"
    assert sorted(out["written"]) == ["evaluator.sh", "launch.sh", "metrics.yaml", "rules.md", "tree.yaml"]
    paths = OmxPaths(root=tmp_path)
    assert paths.profile_file("metrics.yaml").exists()


def test_init_accepts_metrics_json(tmp_path, capsys):
    metrics = {
        "pending_approval": True, "output_root": "out",
        "metrics": ["a"], "views": ["v"], "aggs": ["g"], "sources": ["s"],
        "run_id_regex": None, "keep_policy": "pass_only", "score_formula": None,
    }
    rc = main(["init", "--root", str(tmp_path), "--metrics-json", json.dumps(metrics)])
    assert rc == 0
    loaded = yaml.safe_load(OmxPaths(root=tmp_path).profile_file("metrics.yaml").read_text())
    assert loaded["metrics"] == ["a"]
    assert loaded["output_root"] == "out"


def test_init_bad_schema_rc2(tmp_path, capsys):
    bad = '{"keep_policy": "nope"}'
    rc = main(["init", "--root", str(tmp_path), "--metrics-json", bad])
    assert rc == 2


def test_init_malformed_json_rc2(tmp_path):
    # genuinely malformed JSON -> json.loads raises -> SystemExit -> rc 2
    # (distinct path from a schema violation, which is valid JSON)
    rc = main(["init", "--root", str(tmp_path), "--metrics-json", "not-json{"])
    assert rc == 2


def test_init_refuses_overwrite_rc2(tmp_path):
    assert main(["init", "--root", str(tmp_path)]) == 0
    assert main(["init", "--root", str(tmp_path)]) == 2


def test_init_force_overwrites(tmp_path):
    assert main(["init", "--root", str(tmp_path)]) == 0
    assert main(["init", "--root", str(tmp_path), "--force"]) == 0


def test_init_unknown_reference_rc2(tmp_path):
    rc = main(["init", "--root", str(tmp_path), "--profile-name", "ghost"])
    assert rc == 2
