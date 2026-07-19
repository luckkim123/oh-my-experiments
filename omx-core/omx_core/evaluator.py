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
import subprocess
from pathlib import Path

from omx_core import clock
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


def _last_nonempty_line(text: str):
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return None


def run_evaluator(command: str, cwd, *, timeout: int = 600) -> dict:
    """Run `command` (shell) in `cwd`; parse its LAST non-empty stdout line.

    Returns an EvaluationRecord dict (mirrors runtime.ts AutoresearchEvaluationRecord):
      {command, ran_at, status: pass|fail|error, [pass], [score], exit_code,
       stdout, stderr, [parse_error]}.
    Fault-tolerant by RECORDING: a non-zero exit, timeout, empty stdout, or an
    unparseable last line all yield status='error' (never raises) so the decision
    tree turns it into 'discard' (evaluator-error). The pure parser still loud-fails;
    this runner catches that and records it. Mirrors runtime.ts:586-636.
    """
    ran_at = clock.now_iso()
    cwd = str(Path(cwd))
    try:
        proc = subprocess.run(
            command, shell=True, cwd=cwd, capture_output=True, text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return {
            "command": command, "ran_at": ran_at, "status": "error",
            "exit_code": None,
            "stdout": (e.stdout or "") if isinstance(e.stdout, str) else "",
            "stderr": (e.stderr or "") if isinstance(e.stderr, str) else "",
            "parse_error": f"timeout after {timeout}s",
            "fault_class": "timeout",
        }
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return {
            "command": command, "ran_at": ran_at, "status": "error",
            "exit_code": proc.returncode, "stdout": stdout, "stderr": stderr,
            "parse_error": "evaluator exited non-zero",
            "fault_class": "nonzero_exit",
        }
    last = _last_nonempty_line(stdout)
    if last is None:
        return {
            "command": command, "ran_at": ran_at, "status": "error",
            "exit_code": proc.returncode, "stdout": stdout, "stderr": stderr,
            "parse_error": "evaluator produced no parseable stdout line",
            "fault_class": "empty_stdout",
        }
    try:
        parsed = parse_evaluator_result(last)
    except EvaluatorError as e:
        return {
            "command": command, "ran_at": ran_at, "status": "error",
            "exit_code": proc.returncode, "stdout": stdout, "stderr": stderr,
            "parse_error": str(e),
            "fault_class": "unparseable",
        }
    record = {
        "command": command, "ran_at": ran_at,
        "status": "pass" if parsed["pass"] else "fail",
        "pass": parsed["pass"], "exit_code": proc.returncode,
        "stdout": stdout, "stderr": stderr,
    }
    if "score" in parsed:
        record["score"] = parsed["score"]
    return record
