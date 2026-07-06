"""Task 12 — probe-novelty scans campaign + run ledgers for outcomes (spec 2.9)."""
import json

from omx_core.cli import main

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
            {"status": "discard",
             "description": ("entropy floor widen constraint margin schedule "
                             "plateau attitude error metric probe")}]}))
    capsys.readouterr()
    rc = main(["probe-novelty", "--proposal", str(fp), "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert any(h["event"] == "discard" for h in out["ledger_hits"])


def test_no_ledgers_is_quiet(tmp_path, capsys):
    fp = _proposal(tmp_path)
    rc = main(["probe-novelty", "--proposal", str(fp), "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ledger_hits"] == []
