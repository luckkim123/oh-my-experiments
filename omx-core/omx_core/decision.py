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
import statistics

from omx_core.evaluator import EvaluatorError

_VALID = ("pass_only", "score_improvement")

# k in `mean_new - last_kept_score > k * seed_std` (opt-in multi-seed
# significance gate, see decide_outcome). k=2.0 ~ requires the improvement to
# clear ~2 standard deviations of the new run's own seed noise.
SEED_GATE_K = 2.0


def seed_stats(scores) -> tuple:
    """mean/std/n for a list of per-seed scores (stdlib statistics only — no
    pandas dependency here). Mirrors reduce/summarize.py's add_cv mean+std
    pair, just without the DataFrame. n<2 -> std=0.0 (nothing to measure
    variance against, so the caller's n-guard falls back to a bare compare)."""
    n = len(scores)
    mean = statistics.fmean(scores)
    std = statistics.pstdev(scores) if n > 1 else 0.0
    return mean, std, n


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
        (opt-in: if evaluation carries score_std/score_n from N>=2 seeds with
         nonzero std, gate on mean_new - last_kept_score > SEED_GATE_K *
         score_std instead of the bare '>' — see the branch below)
      else                             -> discard (no improvement)
    """
    if keep_policy not in _VALID:
        raise EvaluatorError(
            f"decide_outcome keep_policy must be normalized to one of {list(_VALID)}, "
            f"got {keep_policy!r} (call parse_keep_policy first).")
    if evaluation is None or evaluation.get("status") == "error":
        fault = (evaluation or {}).get("fault_class")
        note = "candidate discarded because evaluator errored or crashed"
        if fault:
            note = f"candidate discarded because evaluator errored ({fault})"
        return _d("discard", "evaluator error", False, evaluation, note)
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
    # ponytail: opt-in multi-seed significance gate. score_std/score_n are only
    # present on an evaluation dict when the caller aggregated N per-seed runs
    # (e.g. `omx eval --seeds N`, N>=2) into a mean+std pair — the single-seed
    # default path never sets them, so this branch is unreachable there and
    # the bare '>' below stays byte-identical to the pre-existing behavior.
    # Simplification: score_std is the NEW run's seed std only — last_kept_score
    # is a bare float with no stored variance (the ledger doesn't track
    # multi-seed baselines yet), so this isn't a true two-sample pooled std.
    # Upgrade path: once the ledger stores last_kept_std/last_kept_n, pool both
    # sides' variance instead of trusting the new side alone.
    score_std = evaluation.get("score_std")
    score_n = evaluation.get("score_n")
    if _is_number(score_std) and isinstance(score_n, int) and score_n > 1 and score_std > 0:
        if score - last_kept_score > SEED_GATE_K * score_std:
            return _d("keep", f"score improved beyond seed-noise gate (k={SEED_GATE_K})",
                      True, evaluation,
                      "candidate kept because the mean score improvement exceeded "
                      f"{SEED_GATE_K}x the seed std across {score_n} seeds")
        return _d("discard", f"score improvement within seed-noise gate (k={SEED_GATE_K})",
                  False, evaluation,
                  "candidate discarded because the improvement did not clear the "
                  f"{SEED_GATE_K}x seed-std significance gate across {score_n} seeds")
    if score > last_kept_score:
        return _d("keep", "score improved over last kept score", True, evaluation,
                  "candidate kept because evaluator score increased")
    return _d("discard", "score did not improve", False, evaluation,
              "candidate discarded because score was not better than the baseline")
