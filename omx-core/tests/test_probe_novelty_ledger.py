"""Task 12 — probe-novelty scans campaign + run ledgers for outcomes (R1 spec 3.10 residue)."""
import json

from omx_core.cli import main
from omx_core.ledger import record_iteration, seed_ledger
from omx_core.omx_paths import OmxPaths

PROPOSAL = """\
# Proposal
Increase the entropy floor and widen the constraint margin schedule to probe
the plateau hypothesis on the attitude error metric.
"""


def _proposal(tmp_path):
    fp = tmp_path / "proposal.md"
    fp.write_text(PROPOSAL, encoding="utf-8")
    return fp


def test_campaign_ledger_hit_reports_outcome(tmp_path, capsys):
    fp = _proposal(tmp_path)
    assert main(["campaign-init", "--root", str(tmp_path), "--id", "camp_a"]) == 0
    assert main(["campaign-log", "--root", str(tmp_path), "--id", "camp_a",
                 "--event", "discarded", "--run", "alpha_t1_260601_120000",
                 "--data", json.dumps({"note": ("entropy floor widen constraint "
                                                "margin schedule plateau attitude "
                                                "error metric probe")})]) == 0
    capsys.readouterr()
    rc = main(["probe-novelty", "--proposal", str(fp), "--root", str(tmp_path)])
    assert rc == 0                                     # warn-only, never fails
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["ledger_hits"], "campaign ledger hit expected"
    hit = out["ledger_hits"][0]
    assert hit["event"] == "discarded" and hit["run_id"] == "alpha_t1_260601_120000"
    assert "discarded" in captured.err                 # outcome named on stderr


def test_run_ledger_hit(tmp_path, capsys):
    fp = _proposal(tmp_path)
    run_dir = tmp_path / ".omx" / "runs" / "alpha_t2_260602_120000"
    run_dir.mkdir(parents=True)
    (run_dir / "ledger.json").write_text(json.dumps({
        "schema_version": 1, "entries": [
            {"decision": "discard",
             "description": ("entropy floor widen constraint margin schedule "
                             "plateau attitude error metric probe")}]}))
    capsys.readouterr()
    rc = main(["probe-novelty", "--proposal", str(fp), "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert any(h["event"] == "discard" for h in out["ledger_hits"])


def test_run_ledger_hit_via_real_writer(tmp_path, capsys):
    # Schema-drift guard: writes via the actual production writer
    # (record_iteration) instead of a hand-built fixture, so a field-name
    # mismatch between the scanner and omx_core.ledger's real schema (entries
    # use "decision", not "status") gets caught here rather than only in prod.
    fp = _proposal(tmp_path)
    paths = OmxPaths(root=tmp_path)
    run_id = "alpha_t3_260603_120000"
    seed_ledger(paths, run_id, baseline_commit="base000", keep_policy="score_improvement")
    decision = {
        "decision": "discard", "decision_reason": "no improvement", "keep": False,
        "evaluator": {"status": "pass", "pass": True, "score": 0.1}, "notes": ["n"],
    }
    record_iteration(paths, run_id, iteration=0, decision=decision,
                     candidate_checkpoint="/w/m0.pt", candidate_commit="cand000",
                     description=("entropy floor widen constraint margin schedule "
                                  "plateau attitude error metric probe"))
    capsys.readouterr()
    rc = main(["probe-novelty", "--proposal", str(fp), "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    hit = next(h for h in out["ledger_hits"] if h["run_id"] == run_id)
    assert hit["event"] == decision["decision"]   # matches the real recorded decision


def test_no_ledgers_is_quiet(tmp_path, capsys):
    fp = _proposal(tmp_path)
    rc = main(["probe-novelty", "--proposal", str(fp), "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ledger_hits"] == []
