"""Task 6 — tree-audit T1-T12 over the violation zoo (spec 2.3)."""
import json

from omx_core.cli import main
from omx_core.tree_audit import audit_tree

from tree_fixtures import GROUPED_TREE_YAML, build_grouped_tree, build_violation_zoo


def _checks(res):
    return {v["check"] for v in res["violations"]}


def test_clean_tree_is_ok(tmp_path):
    fx = build_grouped_tree(tmp_path)
    res = audit_tree(fx["schema"], tmp_path)
    assert res["ok"] is True and res["violations"] == []


def test_zoo_trips_every_check(tmp_path):
    zoo = build_violation_zoo(tmp_path)
    res = audit_tree(zoo["schema"], tmp_path)
    assert res["ok"] is False
    assert _checks(res) == {"T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8",
                            "T9", "T10", "T11", "T12"}


def test_severities_match_spec(tmp_path):
    zoo = build_violation_zoo(tmp_path)
    res = audit_tree(zoo["schema"], tmp_path)
    sev = {v["check"]: v["severity"] for v in res["violations"]}
    assert all(sev[c] == "error" for c in ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T10"))
    assert all(sev[c] == "warn" for c in ("T8", "T9", "T11", "T12"))


def test_t10_carries_declared_message(tmp_path):
    zoo = build_violation_zoo(tmp_path)
    res = audit_tree(zoo["schema"], tmp_path)
    t10 = next(v for v in res["violations"] if v["check"] == "T10")
    assert t10["message"] == "pre-standard fallback dir"


def _install_schema(tmp_path, text=GROUPED_TREE_YAML):
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "tree.yaml").write_text(text, encoding="utf-8")


def test_cli_report_only_rc0_then_strict_rc2(tmp_path, capsys):
    build_violation_zoo(tmp_path)
    _install_schema(tmp_path)
    assert main(["tree-audit", "--root", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["counts"]["error"] >= 1
    assert main(["tree-audit", "--root", str(tmp_path), "--strict"]) == 2


def test_cli_missing_tree_yaml_rc2(tmp_path, capsys):
    rc = main(["tree-audit", "--root", str(tmp_path)])
    assert rc == 2
    assert "tree-codify" in capsys.readouterr().err
