"""v0.9.0 program layer: CLI verbs (program-init/program-status) + auditor
regression (the new .omx/programs/ tree must not trip audit_tree)."""
import json

from omx_core.cli import main
from omx_core.tree import load_tree_schema
from omx_core.tree_audit import audit_tree

# Mirrors test_campaign_drift.py's _make_project / _TREE_YAML.
_TREE_YAML = """\
version: 1
trees:
  index:
    root: experiments
    levels: [group]
run_id:
  grammar: "<label>[_<tag>]_<ts>"
  ts_format: "%y%m%d_%H%M%S"
  tag: optional
run_dir:
  eval_pattern: "eval/<mode>_<ts>"
  eval_modes: [static]
walk:
  ignore: ["legacy", "_*"]
"""


def _make_project(tmp_path, groups):
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    tree_yaml = prof / "tree.yaml"
    tree_yaml.write_text(_TREE_YAML, encoding="utf-8")
    for group, runs in groups.items():
        for run_id in runs:
            (tmp_path / "experiments" / group / run_id).mkdir(parents=True)
    schema = load_tree_schema(tree_yaml)
    return schema, tmp_path


def test_program_init_then_status_happy_path(tmp_path, capsys):
    main(["campaign-init", "--root", str(tmp_path), "--id", "grp_a"])
    capsys.readouterr()
    main(["campaign-init", "--root", str(tmp_path), "--id", "grp_b"])
    capsys.readouterr()

    rc = main(["program-init", "--root", str(tmp_path), "--id", "prog",
               "--campaigns", "grp_a,grp_b"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out.keys()) == {"program_id", "campaigns", "status", "created"}

    rc2 = main(["program-status", "--root", str(tmp_path), "--id", "prog"])
    assert rc2 == 0
    out2 = json.loads(capsys.readouterr().out)
    assert [c["campaign_id"] for c in out2["campaigns"]] == ["grp_a", "grp_b"]


def test_program_init_uninitialized_member_rc2(tmp_path, capsys):
    main(["campaign-init", "--root", str(tmp_path), "--id", "grp_a"])
    capsys.readouterr()

    rc = main(["program-init", "--root", str(tmp_path), "--id", "prog",
               "--campaigns", "grp_a,grp_missing"])
    assert rc == 2
    assert "grp_missing" in capsys.readouterr().err


def test_program_status_default_id_resolution(tmp_path, capsys):
    rc = main(["program-status", "--root", str(tmp_path)])
    assert rc == 2
    capsys.readouterr()

    main(["campaign-init", "--root", str(tmp_path), "--id", "grp_a"])
    capsys.readouterr()
    main(["program-init", "--root", str(tmp_path), "--id", "only",
          "--campaigns", "grp_a"])
    capsys.readouterr()

    rc2 = main(["program-status", "--root", str(tmp_path)])
    assert rc2 == 0
    out = json.loads(capsys.readouterr().out)
    assert out["program_id"] == "only"


def test_program_init_stderr_plan_md_reminder(tmp_path, capsys):
    main(["campaign-init", "--root", str(tmp_path), "--id", "grp_a"])
    capsys.readouterr()

    rc = main(["program-init", "--root", str(tmp_path), "--id", "prog",
               "--campaigns", "grp_a"])
    assert rc == 0
    assert "PLAN.md" in capsys.readouterr().err


def test_auditor_ignores_program_dir(tmp_path):
    schema, base = _make_project(tmp_path, {"grp_a": ["runa_tag_260722_120000"]})
    prog_dir = tmp_path / ".omx" / "programs" / "prog"
    prog_dir.mkdir(parents=True)
    (prog_dir / "program.json").write_text(json.dumps({
        "program_id": "prog", "campaigns": ["grp_a"],
        "status": "active", "created": "2026-07-23T00:00:00+00:00"}))
    (prog_dir / "PLAN.md").write_text("# plan\n")

    result = audit_tree(schema, base)
    assert result["ok"] is True
    assert result["counts"]["error"] == 0
    assert not any("programs" in v["message"] or "programs" in v["path"]
                   for v in result["violations"])
