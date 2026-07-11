import pytest
from omx_core.decision import decide_outcome, parse_keep_policy
from omx_core.evaluator import EvaluatorError


# --- parse_keep_policy (contracts.ts:127-137) ---
def test_keep_policy_canonical():
    assert parse_keep_policy("pass_only") == "pass_only"
    assert parse_keep_policy("score_improvement") == "score_improvement"


def test_keep_policy_case_insensitive():
    assert parse_keep_policy("  PASS_ONLY ") == "pass_only"
    assert parse_keep_policy("Score_Improvement") == "score_improvement"


def test_keep_policy_absent_defaults_score_improvement():
    assert parse_keep_policy(None) == "score_improvement"
    assert parse_keep_policy("") == "score_improvement"


def test_keep_policy_unknown_raises():
    with pytest.raises(EvaluatorError):
        parse_keep_policy("keep_everything")


# helpers
def _eval(status, **kw):
    rec = {"command": "x", "ran_at": "t", "status": status, "exit_code": 0,
           "stdout": "", "stderr": ""}
    rec.update(kw)
    return rec


# --- decide_outcome: error / no-evaluation branch (runtime.ts:697-705) ---
def test_no_evaluation_discards_as_error():
    d = decide_outcome("pass_only", None, None)
    assert d["decision"] == "discard"
    assert "error" in d["decision_reason"].lower()
    assert d["keep"] is False


def test_evaluator_error_record_discards():
    d = decide_outcome("pass_only", None, _eval("error", parse_error="boom"))
    assert d["decision"] == "discard"
    assert d["keep"] is False


# --- !pass branch (runtime.ts:706-713) ---
def test_fail_discards_under_both_policies():
    for pol in ("pass_only", "score_improvement"):
        d = decide_outcome(pol, None, _eval("fail", **{"pass": False}))
        assert d["decision"] == "discard"


# --- pass_only + pass -> keep (runtime.ts:715-722) ---
def test_pass_only_pass_keeps():
    d = decide_outcome("pass_only", None, _eval("pass", **{"pass": True}))
    assert d["decision"] == "keep"
    assert d["keep"] is True


def test_pass_only_keeps_even_without_score():
    d = decide_outcome("pass_only", 0.5, _eval("pass", **{"pass": True}))
    assert d["decision"] == "keep"   # pass_only ignores score entirely


# --- score_improvement bootstrap: no comparable last_kept_score (runtime.ts:724-738) ---
def test_bootstrap_first_numeric_score_keeps():
    d = decide_outcome("score_improvement", None, _eval("pass", **{"pass": True, "score": 0.3}))
    assert d["decision"] == "keep"
    assert "bootstrap" in d["decision_reason"].lower()


# --- score_improvement + pass but NO score -> ambiguous (B5; runtime.ts:739-745) ---
def test_score_improvement_no_score_is_ambiguous():
    d = decide_outcome("score_improvement", None, _eval("pass", **{"pass": True}))
    assert d["decision"] == "ambiguous"
    assert d["keep"] is False


def test_score_improvement_no_score_ambiguous_even_with_prior_baseline():
    # last_kept_score numeric but candidate has no score -> not comparable -> ambiguous
    # (the subtle OMC branch most re-impls get wrong: runtime.ts:724-745)
    d = decide_outcome("score_improvement", 0.5, _eval("pass", **{"pass": True}))
    assert d["decision"] == "ambiguous"


# --- score_improvement comparable: improvement vs not (runtime.ts:747-762) ---
def test_score_improves_keeps():
    d = decide_outcome("score_improvement", 0.5, _eval("pass", **{"pass": True, "score": 0.7}))
    assert d["decision"] == "keep"


def test_score_not_better_discards():
    d = decide_outcome("score_improvement", 0.5, _eval("pass", **{"pass": True, "score": 0.5}))
    assert d["decision"] == "discard"   # strictly greater required; equal discards
    d2 = decide_outcome("score_improvement", 0.5, _eval("pass", **{"pass": True, "score": 0.4}))
    assert d2["decision"] == "discard"


def test_decision_always_carries_evaluator_and_notes():
    d = decide_outcome("score_improvement", 0.5, _eval("pass", **{"pass": True, "score": 0.7}))
    assert d["evaluator"] is not None
    assert isinstance(d["notes"], list) and d["notes"]


def test_decide_outcome_rejects_unnormalized_policy():
    # decide_outcome takes a REQUIRED keep_policy and loud-fails on an invalid one
    # (no silent fall-through to score_improvement). Symmetry with the repo's
    # no-silent-fallback rule; callers pre-normalize via parse_keep_policy.
    with pytest.raises(EvaluatorError):
        decide_outcome("Pass_Only", None, _eval("pass", **{"pass": True}))


# --- R4 T9: fault_class propagated into the error note ---

def test_error_note_carries_fault_class():
    from omx_core.decision import decide_outcome
    d = decide_outcome("pass_only", None,
                       _eval("error", parse_error="x", fault_class="timeout"))
    assert d["decision_reason"] == "evaluator error"  # unchanged (downstream stability)
    assert "(timeout)" in d["notes"][0]


def test_error_note_without_fault_class_is_stable():
    from omx_core.decision import decide_outcome
    d = decide_outcome("pass_only", None, _eval("error", parse_error="x"))
    # no fault_class present -> note still reads sensibly (no "(None)")
    assert "(None)" not in d["notes"][0]
