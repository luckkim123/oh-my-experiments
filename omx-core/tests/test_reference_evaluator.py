import os
from omx_core.omx_paths import OmxPaths
from omx_core.evaluator import run_evaluator, parse_evaluator_result
from omx_core.decision import decide_outcome


def test_reference_evaluator_resolves_committed_file(tmp_path):
    # the strict resolves-success assertion deferred from Task 1 — the file ships here
    p = OmxPaths(tmp_path)
    ev = p.reference_evaluator("isaaclab")
    assert ev.name == "evaluator.sh"
    assert ev.parent.name == "isaaclab"
    assert ev.exists()


def test_reference_evaluator_file_is_executable(tmp_path):
    p = OmxPaths(tmp_path)
    ev = p.reference_evaluator("isaaclab")
    assert os.access(ev, os.X_OK)   # committed executable bit


def test_reference_evaluator_emits_contract_json(tmp_path):
    p = OmxPaths(tmp_path)
    ev = p.reference_evaluator("isaaclab")
    rec = run_evaluator(f"bash {ev}", cwd=tmp_path)
    # stub ships pass_only: a parseable {pass: bool} verdict, status pass/fail
    assert rec["status"] in ("pass", "fail")
    assert isinstance(rec["pass"], bool)


def test_reference_last_line_parses_through_contract(tmp_path):
    p = OmxPaths(tmp_path)
    ev = p.reference_evaluator("isaaclab")
    rec = run_evaluator(f"bash {ev}", cwd=tmp_path)
    parsed = parse_evaluator_result(rec["stdout"].splitlines()[-1])
    assert "pass" in parsed


def test_reference_with_pass_only_policy_decides(tmp_path):
    # end-to-end: reference (pass_only) -> decide_outcome keeps on pass
    p = OmxPaths(tmp_path)
    ev = p.reference_evaluator("isaaclab")
    rec = run_evaluator(f"OMX_REF_PASS=1 bash {ev}", cwd=tmp_path)
    d = decide_outcome("pass_only", None, rec)
    assert d["decision"] == "keep"
