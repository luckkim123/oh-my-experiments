import json

import pytest
from omx_core.ledger import (
    RESULTS_HEADER,
    append_decision_log,
    append_ledger_entry,
    append_results_row,
    record_iteration,
    seed_ledger,
)
from omx_core.omx_paths import OmxPaths


def test_results_tsv_header_written_once(tmp_path):
    p = OmxPaths(tmp_path)
    append_results_row(p, "run01", {"iteration": 0, "commit": "abc1234", "pass": True,
                                    "score": 0.5, "status": "keep", "description": "first"})
    append_results_row(p, "run01", {"iteration": 1, "commit": "def5678", "pass": False,
                                    "score": None, "status": "discard", "description": "second"})
    text = p.results_tsv("run01").read_text()
    assert text.startswith(RESULTS_HEADER)
    assert text.count(RESULTS_HEADER) == 1   # header not duplicated
    rows = text.strip().splitlines()
    assert len(rows) == 3                     # header + 2
    assert "\t" in rows[1]
    assert rows[2].split("\t")[3] == ""       # None score -> blank cell


def test_ledger_json_accumulates_entries(tmp_path):
    p = OmxPaths(tmp_path)
    append_ledger_entry(p, "run01", {"iteration": 0, "decision": "keep",
                                     "decision_reason": "x", "candidate_checkpoint": "m0.pt"})
    append_ledger_entry(p, "run01", {"iteration": 1, "decision": "discard",
                                     "decision_reason": "y", "candidate_checkpoint": "m1.pt"})
    data = json.loads(p.ledger_json("run01").read_text())
    assert data["schema_version"] == 1
    assert len(data["entries"]) == 2
    assert data["entries"][1]["decision"] == "discard"


def test_decision_log_prose_blocks(tmp_path):
    p = OmxPaths(tmp_path)
    append_decision_log(p, "run01", {"iteration": 0, "decision": "keep",
        "description": "tune kd", "reason": "score up",
        "evaluator": {"status": "pass", "pass": True, "score": 0.7}, "notes": ["n1"]})
    text = p.decision_log("run01").read_text()
    assert text.startswith("# OMX Decision Log")
    assert "## Iteration 0 — keep" in text
    assert "- Score: 0.7" in text
    assert "  - n1" in text


# --- B6: baseline_commit is SEEDED at run-init and INVARIANT across keeps/discards ---
def test_seed_ledger_sets_invariant_baseline(tmp_path):
    p = OmxPaths(tmp_path)
    seed_ledger(p, "run01", baseline_commit="base000", keep_policy="score_improvement")
    led = json.loads(p.ledger_json("run01").read_text())
    assert led["baseline_commit"] == "base000"
    assert led["keep_policy"] == "score_improvement"
    assert led["last_kept_commit"] is None         # not advanced yet
    assert led["last_kept_checkpoint"] is None


def test_baseline_commit_invariant_across_keep_and_discard(tmp_path):
    p = OmxPaths(tmp_path)
    seed_ledger(p, "run01", baseline_commit="base000", keep_policy="score_improvement")
    keep = {"decision": "keep", "decision_reason": "r", "keep": True,
            "evaluator": {"status": "pass", "pass": True, "score": 0.7}, "notes": ["n"]}
    record_iteration(p, "run01", iteration=0, decision=keep,
                     candidate_checkpoint="/w/m0.pt", candidate_commit="cand111", description="x")
    disc = {"decision": "discard", "decision_reason": "r", "keep": False,
            "evaluator": {"status": "pass", "pass": True, "score": 0.4}, "notes": ["n"]}
    record_iteration(p, "run01", iteration=1, decision=disc,
                     candidate_checkpoint="/w/m1.pt", candidate_commit="cand222", description="y")
    led = json.loads(p.ledger_json("run01").read_text())
    # baseline_commit is the PRE-experiment anchor — never the first kept candidate's commit
    assert led["baseline_commit"] == "base000"
    assert led["last_kept_commit"] == "cand111"   # config pointer advanced on keep only


# --- B6: keep ADVANCES the checkpoint pointer (ledger + mirror) ---
def test_record_iteration_keep_advances_checkpoint_and_commit(tmp_path):
    p = OmxPaths(tmp_path)
    seed_ledger(p, "run01", baseline_commit="base000", keep_policy="score_improvement")
    decision = {"decision": "keep", "decision_reason": "score up", "keep": True,
                "evaluator": {"status": "pass", "pass": True, "score": 0.7}, "notes": ["n"]}
    record_iteration(p, "run01", iteration=0, decision=decision,
                     candidate_checkpoint="/w/model_100.pt", candidate_commit="abc1234",
                     description="tune")
    led = json.loads(p.ledger_json("run01").read_text())
    assert led["last_kept_checkpoint"] == "/w/model_100.pt"   # advanced
    assert led["last_kept_commit"] == "abc1234"               # config side advanced
    assert led["last_kept_score"] == 0.7
    ptr = json.loads(p.checkpoint_pointer_json("run01").read_text())
    assert ptr["last_kept_checkpoint"] == "/w/model_100.pt"   # mirror written


# --- B6: discard LEAVES the pointer (no advance, NO git/rm on weights) ---
def test_record_iteration_discard_leaves_checkpoint(tmp_path):
    p = OmxPaths(tmp_path)
    seed_ledger(p, "run01", baseline_commit="base000", keep_policy="score_improvement")
    keep = {"decision": "keep", "decision_reason": "r", "keep": True,
            "evaluator": {"status": "pass", "pass": True, "score": 0.7}, "notes": ["n"]}
    record_iteration(p, "run01", iteration=0, decision=keep,
                     candidate_checkpoint="/w/model_100.pt", candidate_commit="aaa1111",
                     description="keep it")
    disc = {"decision": "discard", "decision_reason": "no improvement", "keep": False,
            "evaluator": {"status": "pass", "pass": True, "score": 0.4}, "notes": ["n"]}
    discarded = tmp_path / "model_200.pt"
    discarded.write_text("weights")
    record_iteration(p, "run01", iteration=1, decision=disc,
                     candidate_checkpoint=str(discarded), candidate_commit="bbb2222",
                     description="reject it")
    led = json.loads(p.ledger_json("run01").read_text())
    assert led["last_kept_checkpoint"] == "/w/model_100.pt"   # LEFT at the kept one
    assert led["last_kept_commit"] == "aaa1111"               # config pointer unchanged
    assert led["last_kept_score"] == 0.7                       # baseline unchanged
    assert discarded.exists()                                  # NO rm on weights
    assert discarded.read_text() == "weights"                  # NO git op / mutation
    ptr = json.loads(p.checkpoint_pointer_json("run01").read_text())
    assert ptr["last_kept_checkpoint"] == "/w/model_100.pt"


# --- B6: a NON-keep status beyond 'discard' (ambiguous) also LEAVES the pointer ---
def test_record_iteration_ambiguous_leaves_checkpoint(tmp_path):
    p = OmxPaths(tmp_path)
    seed_ledger(p, "run01", baseline_commit="base000", keep_policy="score_improvement")
    keep = {"decision": "keep", "decision_reason": "r", "keep": True,
            "evaluator": {"status": "pass", "pass": True, "score": 0.7}, "notes": ["n"]}
    record_iteration(p, "run01", iteration=0, decision=keep,
                     candidate_checkpoint="/w/model_100.pt", candidate_commit="aaa1111",
                     description="keep it")
    amb = {"decision": "ambiguous", "decision_reason": "pass without numeric score",
           "keep": False, "evaluator": {"status": "pass", "pass": True}, "notes": ["n"]}
    record_iteration(p, "run01", iteration=1, decision=amb,
                     candidate_checkpoint="/w/model_200.pt", candidate_commit="bbb2222",
                     description="ambiguous one")
    led = json.loads(p.ledger_json("run01").read_text())
    assert led["last_kept_checkpoint"] == "/w/model_100.pt"   # pointer LEFT for ambiguous too
    assert led["last_kept_commit"] == "aaa1111"


def test_record_iteration_writes_all_three_artifacts(tmp_path):
    p = OmxPaths(tmp_path)
    seed_ledger(p, "run01", baseline_commit="base000", keep_policy="pass_only")
    d = {"decision": "keep", "decision_reason": "r", "keep": True,
         "evaluator": {"status": "pass", "pass": True, "score": 0.7}, "notes": ["n"]}
    record_iteration(p, "run01", iteration=0, decision=d,
                     candidate_checkpoint="/w/m.pt", candidate_commit="c", description="x")
    assert p.results_tsv("run01").exists()
    assert p.ledger_json("run01").exists()
    assert p.decision_log("run01").exists()
    # atomic: no .tmp leftovers in the run dir
    leftovers = [f.name for f in p.run_dir("run01").iterdir() if f.name.endswith(".tmp")]
    assert leftovers == []


# --- R5 T5: absent-vs-corrupt split + health mirror (D-R5-6) ---

def test_read_run_ledger_absent_raises_plain_omxerror(tmp_path):
    from omx_core.ledger import LedgerCorruptError, read_run_ledger
    from omx_core.omx_paths import OmxError
    p = OmxPaths(tmp_path)
    with pytest.raises(OmxError) as ei:
        read_run_ledger(p, "run1")
    # absence is NOT corruption: a plain OmxError, never the corrupt subtype
    assert not isinstance(ei.value, LedgerCorruptError)
    assert "no ledger" in str(ei.value)


def test_read_run_ledger_corrupt_raises_ledger_corrupt(tmp_path):
    from omx_core.ledger import LedgerCorruptError, read_run_ledger
    p = OmxPaths(tmp_path)
    target = p.ledger_json("run1")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{not valid json")
    with pytest.raises(LedgerCorruptError):
        read_run_ledger(p, "run1")


def test_ledger_corrupt_is_omxerror_subclass():
    from omx_core.ledger import LedgerCorruptError
    from omx_core.omx_paths import OmxError
    assert issubclass(LedgerCorruptError, OmxError)


def test_record_iteration_writes_health_mirror_when_armed(tmp_path):
    # a loop armed for run1 -> record_iteration mirrors loop_health into the
    # active_loop envelope AFTER the ledger writes.
    from omx_core.ledger import record_iteration, seed_ledger
    from omx_core.loop import arm_loop
    from omx_core.state import load_state
    p = OmxPaths(tmp_path)
    arm_loop(p, run_id="run1", now_iso="2026-07-11T10:00:00+00:00",
             max_runtime_s=10 ** 8, session_id="s")
    seed_ledger(p, "run1", baseline_commit="abc", keep_policy="pass_only")
    record_iteration(p, "run1", iteration=0,
                     decision={"decision": "discard", "keep": False, "evaluator": None,
                               "decision_reason": "manual record", "notes": []},
                     candidate_checkpoint="m0.pt", candidate_commit="c0",
                     description="d")
    mirror = load_state(p)["active_loop"]["health_mirror"]
    assert mirror["consecutive_discards"] == 1
    assert mirror["consecutive_faults"] == 0
    assert mirror["at_iteration"] == 0


def test_record_iteration_no_mirror_when_not_armed(tmp_path):
    # no loop armed (or armed for a DIFFERENT run) -> record writes no mirror.
    from omx_core.ledger import record_iteration, seed_ledger
    from omx_core.state import load_state
    p = OmxPaths(tmp_path)
    seed_ledger(p, "run1", baseline_commit="abc", keep_policy="pass_only")
    record_iteration(p, "run1", iteration=0,
                     decision={"decision": "keep", "keep": True, "evaluator": None,
                               "decision_reason": "manual record", "notes": []},
                     candidate_checkpoint="m0.pt", candidate_commit="c0",
                     description="d")
    assert load_state(p).get("active_loop") is None   # nothing armed -> no envelope
