"""omx_core.decision — re-impl of OMC's keep-policy decision tree (NEVER imported).

Mirrors runtime.ts decideAutoresearchOutcome (lines 665-763) + comparableScore
(661-663) + contracts.ts parseKeepPolicy (127-137), pure Python. No git, no I/O —
a deterministic function from (keep_policy, last_kept_score, evaluation) to a
decision dict. The candidate-status cases (abort/noop/interrupted, runtime.ts:670-695)
belong to exp-loop (#6, which owns the candidate artifact); #2 covers the
evaluation-driven tail of the tree, which is the Claude-free unit-testable part
(design H3).

B5 coupling: under pass_only, score is irrelevant (pass -> keep). Under
score_improvement, a score-less pass is 'ambiguous' (discard) — the loud,
documented coupling contracts.ts leaves implicit.
"""
from omx_core.evaluator import EvaluatorError

_VALID = ("pass_only", "score_improvement")


def parse_keep_policy(raw) -> str:
    """Normalize keep_policy. Absent/empty -> 'score_improvement' (OMC default,
    runtime.ts:651). Unknown string -> loud-fail. Mirrors contracts.ts:127-137."""
    if raw is None:
        return "score_improvement"
    if not isinstance(raw, str):
        raise EvaluatorError("keep_policy must be a string when provided.")
    norm = raw.strip().lower()
    if not norm:
        return "score_improvement"
    if norm in _VALID:
        return norm
    raise EvaluatorError(
        f"keep_policy must be one of {list(_VALID)}, got {raw!r}.")


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _comparable_score(prev, nxt) -> bool:
    """True only when BOTH are numbers (runtime.ts:661-663)."""
    return _is_number(prev) and _is_number(nxt)


def _d(decision, reason, keep, evaluation, note):
    return {"decision": decision, "decision_reason": reason, "keep": keep,
            "evaluator": evaluation, "notes": [note]}


def decide_outcome(keep_policy: str, last_kept_score, evaluation) -> dict:
    """Decide keep/discard/ambiguous from an evaluation record. Pure.

    `keep_policy` is REQUIRED and must already be normalized (one of _VALID) —
    loud-fail otherwise (no silent fall-through). `evaluation` is the dict from
    run_evaluator (or None). Cases, in OMC order:
      no evaluation or status=='error' -> discard (evaluator error)
      pass is falsey                   -> discard
      pass_only & pass                 -> keep
      score_improvement, no comparable last_kept_score:
          candidate score numeric      -> keep   [bootstrap: becomes baseline]
          else                         -> ambiguous (discard; needs numeric score)
      score > last_kept_score          -> keep
      else                             -> discard (no improvement)
    """
    if keep_policy not in _VALID:
        raise EvaluatorError(
            f"decide_outcome keep_policy must be normalized to one of {list(_VALID)}, "
            f"got {keep_policy!r} (call parse_keep_policy first).")
    if evaluation is None or evaluation.get("status") == "error":
        return _d("discard", "evaluator error", False, evaluation,
                  "candidate discarded because evaluator errored or crashed")
    if not evaluation.get("pass"):
        return _d("discard", "evaluator reported failure", False, evaluation,
                  "candidate discarded because evaluator pass=false")
    if keep_policy == "pass_only":
        return _d("keep", "pass_only keep policy accepted evaluator pass=true",
                  True, evaluation,
                  "candidate kept because policy is pass_only")
    score = evaluation.get("score")
    if not _comparable_score(last_kept_score, score):
        if _is_number(score):
            return _d("keep", "[bootstrap] first comparable score in score_improvement run",
                      True, evaluation,
                      "candidate kept; no prior comparable score -> new baseline")
        return _d("ambiguous", "evaluator pass without numeric score", False, evaluation,
                  "candidate discarded; score_improvement requires a numeric score")
    if score > last_kept_score:
        return _d("keep", "score improved over last kept score", True, evaluation,
                  "candidate kept because evaluator score increased")
    return _d("discard", "score did not improve", False, evaluation,
              "candidate discarded because score was not better than the baseline")
