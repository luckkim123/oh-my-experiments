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
