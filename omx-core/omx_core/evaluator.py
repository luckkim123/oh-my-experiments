"""omx_core.evaluator — re-implementation of OMC's evaluator contract (NEVER imported).

Mirrors src/autoresearch/contracts.ts parseEvaluatorResult (lines 178-201) and
runtime.ts runAutoresearchEvaluator (lines 586-636), in pure Python:
  - parse_evaluator_result: loud-fail JSON -> {pass} or {pass, score}.
  - run_evaluator (Task 3): subprocess, LAST stdout line parsed, fault-recorded.

The parser is strictly loud-fail (raises EvaluatorError); the runner is
fault-tolerant-by-RECORDING (captures the failure into the EvaluationRecord so
the decision tree turns it into 'discard', never crashing the loop).
"""
import json

from omx_core.omx_paths import OmxError


class EvaluatorError(OmxError):
    """Raised by the loud-fail parser on bad JSON / missing pass / non-numeric score."""


def _is_number(x) -> bool:
    # JSON numbers parse to int/float; reject bool (JSON true/false is not a number,
    # but Python bool is an int subclass, so exclude it explicitly).
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def parse_evaluator_result(raw: str) -> dict:
    """Parse evaluator stdout JSON. Returns {'pass': bool} or {'pass', 'score'}.

    Loud-fail (EvaluatorError) on: invalid JSON, non-object, missing/non-bool
    'pass', or 'score' present but non-numeric. Mirrors contracts.ts:178-201.
    (OMC uses a bare `catch {}` around JSON.parse; (ValueError, TypeError) is the
    faithful Python equivalent — json.loads raises JSONDecodeError<:ValueError on
    bad JSON, TypeError on non-str input.)
    """
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise EvaluatorError(
            "Evaluator output must be valid JSON with required boolean pass "
            "and optional numeric score.") from e
    if not isinstance(parsed, dict):
        raise EvaluatorError("Evaluator output must be a JSON object.")
    if not isinstance(parsed.get("pass"), bool):
        raise EvaluatorError("Evaluator output must include boolean pass.")
    if "score" in parsed and not _is_number(parsed["score"]):
        raise EvaluatorError("Evaluator output score must be numeric when provided.")
    if "score" in parsed:
        return {"pass": parsed["pass"], "score": parsed["score"]}
    return {"pass": parsed["pass"]}
