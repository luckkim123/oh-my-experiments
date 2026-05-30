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
