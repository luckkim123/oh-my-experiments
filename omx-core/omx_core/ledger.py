"""omx_core.ledger — the autoresearch 3-artifact trio + B6 hybrid-revert pointer.

Writes results.tsv (terse rows) + ledger.json (structured ledger) + decision-log.md
(prose), all through omx_paths getters with atomic writes. Mirrors runtime.ts
appendAutoresearchResultsRow / appendAutoresearchLedgerEntry / appendDecisionLog,
terse Python.

B6 hybrid revert (LOCKED schema, design §0.1 / §9 carry):
  - CONFIG edits revert via git -> ledger records baseline_commit (the PRE-experiment
    anchor, SEEDED at run-init by seed_ledger and INVARIANT) + last_kept_commit
    (advances on keep). #2 only RECORDS these; exp-loop (#6) runs the actual git revert.
  - TRAINED WEIGHTS revert via a POINTER, never a git/rm op: last_kept_checkpoint.
    keep advances it to the candidate's checkpoint; any non-keep (discard/ambiguous/
    noop/abort/interrupted/error) LEAVES it. #2 performs ZERO filesystem mutation on
    any weight file — physical checkpoint GC is #6's job (deferred per §9, out of scope
    here). A mirror checkpoint-pointer.json lets #6 read the pointer without parsing
    the whole ledger; ledger and mirror are two sequential atomic writes, LEDGER
    AUTHORITATIVE (mirror may transiently lag on crash).
"""
import json

from omx_core.omx_paths import OmxPaths, atomic_path

# byte-identical to runtime.ts AUTORESEARCH_RESULTS_HEADER (line 146)
RESULTS_HEADER = "iteration\tcommit\tpass\tscore\tstatus\tdescription\n"


def _pass_cell(v):
    return "" if v is None else ("true" if v else "false")


def _score_cell(v):
    # repr(float) matches JS String(value) for the score range we use (0.5, 0.7, 3,
    # None->''); they can diverge on extreme exponents (e.g. 1e-05), which no contract
    # path depends on (scores round-trip through JSON, not this readability cell).
    return "" if v is None else repr(v) if isinstance(v, float) else str(v)


def _default_ledger() -> dict:
    return {"schema_version": 1, "keep_policy": None,
            "baseline_commit": None, "last_kept_commit": None,
            "last_kept_score": None, "last_kept_checkpoint": None, "entries": []}


def _load_ledger(target) -> dict:
    if target.exists():
        return json.loads(target.read_text())
    return _default_ledger()


def append_results_row(paths: OmxPaths, run_id, row: dict) -> None:
    """Append one terse TSV row; write the header first if the file is new."""
    target = paths.results_tsv(run_id)
    existing = target.read_text() if target.exists() else RESULTS_HEADER
    line = "\t".join([
        str(row["iteration"]), str(row["commit"]),
        _pass_cell(row.get("pass")), _score_cell(row.get("score")),
        str(row["status"]), str(row["description"]),
    ]) + "\n"
    with atomic_path(target) as tmp:
        tmp.write_text(existing + line)


def append_ledger_entry(paths: OmxPaths, run_id, entry: dict) -> None:
    """Append one structured entry to ledger.json (accumulating, atomic)."""
    target = paths.ledger_json(run_id)
    led = _load_ledger(target)
    led["entries"].append(entry)
    with atomic_path(target) as tmp:
        tmp.write_text(json.dumps(led, indent=2, sort_keys=True))


def append_decision_log(paths: OmxPaths, run_id, entry: dict) -> None:
    """Append one prose decision block to decision-log.md (mirrors appendDecisionLog)."""
    target = paths.decision_log(run_id)
    lines = [f"## Iteration {entry['iteration']} — {entry['decision']}", "",
             f"- Description: {entry['description']}", f"- Reason: {entry['reason']}"]
    ev = entry.get("evaluator")
    if ev:
        score = ev.get("score")
        lines += [f"- Evaluator status: {ev.get('status')}",
                  f"- Pass: {ev.get('pass', '')}",
                  f"- Score: {score if isinstance(score, (int, float)) else ''}"]
    notes = entry.get("notes") or []
    if notes:
        lines.append("- Notes:")
        lines += [f"  - {n}" for n in notes]
    lines += ["", ""]
    existing = target.read_text() if target.exists() else "# OMX Decision Log\n\n"
    with atomic_path(target) as tmp:
        tmp.write_text(existing + "\n".join(lines))


def seed_ledger(paths: OmxPaths, run_id, *, baseline_commit, keep_policy) -> None:
    """Initialize ledger.json with the PRE-experiment anchor (B6).

    baseline_commit is the config git-revert target — the point a revert unwinds TO.
    It is set ONCE here at run-init and held INVARIANT; record_iteration never
    derives it from a kept candidate. Idempotent-ish: re-seeding overwrites the
    anchor fields but is intended to be called exactly once before iteration 0.
    """
    target = paths.ledger_json(run_id)
    led = _load_ledger(target)
    led["baseline_commit"] = baseline_commit
    led["keep_policy"] = keep_policy
    with atomic_path(target) as tmp:
        tmp.write_text(json.dumps(led, indent=2, sort_keys=True))


def record_iteration(paths: OmxPaths, run_id, *, iteration, decision,
                     candidate_checkpoint, candidate_commit, description) -> None:
    """Write all three artifacts for one iteration AND apply the B6 pointer rule.

    `decision` is the dict from decide_outcome. On keep -> advance last_kept_commit
    /last_kept_checkpoint (and last_kept_score when numeric) to this candidate;
    otherwise LEAVE them. baseline_commit is NEVER touched here (seeded by
    seed_ledger). Performs NO filesystem op on any weight file (only the pointer
    string moves).
    """
    ev = decision.get("evaluator") or {}
    score = ev.get("score")
    status = decision["decision"]
    keep = decision.get("keep", False)

    # 1) results.tsv
    append_results_row(paths, run_id, {
        "iteration": iteration, "commit": candidate_commit,
        "pass": ev.get("pass"), "score": score, "status": status,
        "description": description,
    })
    # 2) ledger.json (entry + B6 pointer advance/leave in the same atomic write)
    target = paths.ledger_json(run_id)
    led = _load_ledger(target)
    led["entries"].append({
        "iteration": iteration, "decision": status,
        "decision_reason": decision["decision_reason"],
        "candidate_checkpoint": candidate_checkpoint,
        "candidate_commit": candidate_commit,
        "evaluator": ev or None, "notes": decision.get("notes", []),
        "description": description,
    })
    if keep:
        led["last_kept_checkpoint"] = candidate_checkpoint   # ADVANCE (pointer only)
        led["last_kept_commit"] = candidate_commit
        # leave-prior on a score-less keep (pass_only): only advance when numeric.
        # matches the per-iteration OMC path (runtime.ts:1466); #6 must not "fix" to null.
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            led["last_kept_score"] = score
    # non-keep (discard/ambiguous/...): pointer LEFT untouched; NO git/rm on weights.
    with atomic_path(target) as tmp:
        tmp.write_text(json.dumps(led, indent=2, sort_keys=True))
    # 3) checkpoint-pointer.json mirror (derived; ledger is authoritative)
    ptr_target = paths.checkpoint_pointer_json(run_id)
    with atomic_path(ptr_target) as tmp:
        tmp.write_text(json.dumps(
            {"last_kept_checkpoint": led["last_kept_checkpoint"]},
            indent=2, sort_keys=True))
    # 4) decision-log.md
    append_decision_log(paths, run_id, {
        "iteration": iteration, "decision": status, "description": description,
        "reason": decision["decision_reason"], "evaluator": ev or None,
        "notes": decision.get("notes", []),
    })
