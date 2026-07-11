import json
import pytest
from omx_core.evaluator import parse_evaluator_result, EvaluatorError
from omx_core.omx_paths import OmxError


def test_pass_only_returns_pass_no_score():
    assert parse_evaluator_result('{"pass": true}') == {"pass": True}


def test_pass_with_numeric_score():
    assert parse_evaluator_result('{"pass": false, "score": 0.42}') == {"pass": False, "score": 0.42}


def test_integer_score_is_numeric():
    assert parse_evaluator_result('{"pass": true, "score": 3}') == {"pass": True, "score": 3}


def test_bad_json_raises():
    with pytest.raises(EvaluatorError):
        parse_evaluator_result("{not valid json")


def test_non_object_raises():
    with pytest.raises(EvaluatorError):
        parse_evaluator_result("[1, 2, 3]")
    with pytest.raises(EvaluatorError):
        parse_evaluator_result("true")


def test_missing_pass_raises():
    with pytest.raises(EvaluatorError):
        parse_evaluator_result('{"score": 0.5}')


def test_pass_must_be_bool_not_truthy():
    # contracts.ts requires typeof === 'boolean'; 1/"true" must NOT pass
    with pytest.raises(EvaluatorError):
        parse_evaluator_result('{"pass": 1}')
    with pytest.raises(EvaluatorError):
        parse_evaluator_result('{"pass": "true"}')


def test_non_numeric_score_raises():
    with pytest.raises(EvaluatorError):
        parse_evaluator_result('{"pass": true, "score": "high"}')


def test_bool_score_rejected():
    # JSON true is not a number; Python bool is an int subclass so guard explicitly
    with pytest.raises(EvaluatorError):
        parse_evaluator_result('{"pass": true, "score": true}')


def test_evaluator_error_is_omx_error():
    assert issubclass(EvaluatorError, OmxError)


from omx_core.evaluator import run_evaluator


def test_run_passes_last_line_only(tmp_path):
    # noise on earlier lines must be ignored; LAST non-empty line is the verdict
    rec = run_evaluator('printf "loading...\\nrunning eval\\n{\\"pass\\": true, \\"score\\": 0.9}\\n"', cwd=tmp_path)
    assert rec["status"] == "pass"
    assert rec["pass"] is True
    assert rec["score"] == 0.9
    assert rec["exit_code"] == 0


def test_run_fail_verdict(tmp_path):
    rec = run_evaluator('echo "{\\"pass\\": false}"', cwd=tmp_path)
    assert rec["status"] == "fail"
    assert rec["pass"] is False
    assert "score" not in rec


def test_run_trailing_blank_lines_ignored(tmp_path):
    rec = run_evaluator('printf "{\\"pass\\": true}\\n\\n\\n"', cwd=tmp_path)
    assert rec["status"] == "pass"


def test_run_nonzero_exit_is_error(tmp_path):
    rec = run_evaluator('echo "{\\"pass\\": true}"; exit 7', cwd=tmp_path)
    assert rec["status"] == "error"
    assert rec["exit_code"] == 7


def test_run_unparseable_last_line_is_error(tmp_path):
    rec = run_evaluator('echo "not json at all"', cwd=tmp_path)
    assert rec["status"] == "error"
    assert "parse_error" in rec


def test_run_empty_stdout_is_error(tmp_path):
    rec = run_evaluator('true', cwd=tmp_path)   # exit 0, no stdout
    assert rec["status"] == "error"
    assert "parse_error" in rec


def test_run_timeout_is_error_not_raise(tmp_path):
    rec = run_evaluator('sleep 5', cwd=tmp_path, timeout=1)
    assert rec["status"] == "error"
    assert "timeout" in rec["parse_error"].lower()


def test_run_record_carries_command_and_stdout(tmp_path):
    rec = run_evaluator('echo "{\\"pass\\": true}"', cwd=tmp_path)
    assert "echo" in rec["command"]
    assert "pass" in rec["stdout"]
    assert "ran_at" in rec


# --- R4 T9: fault_class on the four error branches (#9) ---

from omx_core.evaluator import run_evaluator


def test_fault_class_nonzero_exit(tmp_path):
    rec = run_evaluator("exit 3", cwd=str(tmp_path))
    assert rec["status"] == "error"
    assert rec["fault_class"] == "nonzero_exit"
    assert rec["parse_error"] == "evaluator exited non-zero"  # shape uniformity


def test_fault_class_empty_stdout(tmp_path):
    rec = run_evaluator("true", cwd=str(tmp_path))  # rc 0, no stdout
    assert rec["status"] == "error"
    assert rec["fault_class"] == "empty_stdout"


def test_fault_class_unparseable(tmp_path):
    rec = run_evaluator("echo not-json", cwd=str(tmp_path))
    assert rec["status"] == "error"
    assert rec["fault_class"] == "unparseable"


def test_fault_class_timeout(tmp_path):
    rec = run_evaluator("sleep 5", cwd=str(tmp_path), timeout=1)
    assert rec["status"] == "error"
    assert rec["fault_class"] == "timeout"


def test_success_record_has_no_fault_class(tmp_path):
    rec = run_evaluator('echo \'{"pass": true}\'', cwd=str(tmp_path))
    assert rec["status"] == "pass"
    assert "fault_class" not in rec


# --- R4 T9: omx eval error auto-appends a debugging wiki stub (#27) ---

def test_eval_error_appends_wiki_stub(tmp_path, capsys):
    from omx_core import cli
    from omx_core.omx_paths import OmxPaths
    from omx_core.wiki.storage import list_pages
    # a sealed profile is needed so --root doesn't rc-2 on the seal preflight;
    # build the minimal profile + seal the way the seal tests do, OR pass a root
    # with a profile whose seal is ABSENT (eval warns but proceeds). Absent-seal
    # is simplest: create .omx/profile/evaluator.sh so check_seal returns absent.
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "evaluator.sh").write_text("#!/bin/sh\nexit 3\n")
    capsys.readouterr()
    rc = cli.main(["eval", "--command", "exit 3", "--cwd", str(tmp_path),
                   "--root", str(tmp_path)])
    assert rc == 1  # evaluator-broke rc is unchanged
    paths = OmxPaths(root=str(tmp_path))
    pages = list_pages(paths)
    assert any("evaluator_fault_nonzero_exit" in s or "evaluator-fault-nonzero_exit" in s
               for s in pages), pages


def test_eval_error_stub_capture_is_idempotent(tmp_path, capsys):
    from omx_core import cli
    from omx_core.omx_paths import OmxPaths
    from omx_core.wiki.storage import list_pages
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "evaluator.sh").write_text("#!/bin/sh\nexit 3\n")
    for _ in range(2):
        cli.main(["eval", "--command", "exit 3", "--cwd", str(tmp_path),
                  "--root", str(tmp_path)])
    capsys.readouterr()
    paths = OmxPaths(root=str(tmp_path))
    fault_pages = [s for s in list_pages(paths) if "nonzero_exit" in s]
    assert len(fault_pages) == 1  # append-merge: recurrence strengthens ONE page


def test_eval_error_capture_failure_is_nonfatal(tmp_path, capsys, monkeypatch):
    # a capture exception must NOT change the eval rc (grading never breaks on
    # knowledge plumbing). Poison ingest_knowledge to raise.
    from omx_core import cli
    import omx_core.wiki.ingest as ingest_mod
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "evaluator.sh").write_text("#!/bin/sh\nexit 3\n")

    def _boom(*a, **k):
        raise RuntimeError("wiki down")

    monkeypatch.setattr(ingest_mod, "ingest_knowledge", _boom)
    capsys.readouterr()
    rc = cli.main(["eval", "--command", "exit 3", "--cwd", str(tmp_path),
                   "--root", str(tmp_path)])
    assert rc == 1  # still the evaluator-broke rc; the capture failure is swallowed
    # the swallowed failure must still surface a warning on stderr — a
    # load-bearing assertion (no `or True` escape) on the exact warn substring.
    assert "evaluator-fault wiki capture failed" in capsys.readouterr().err.lower()
