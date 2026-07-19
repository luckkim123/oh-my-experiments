import json

from omx_core.cli import main
from omx_core.proposal import lint_proposal, probe_tokens

GOOD = """# Next-experiment proposal — pending approval
run_id: run_a  analysis: diagnose-20260705-120000  proposal: next-20260705-130000

## Diagnosis
Code-path lane: clamp saturates. [EVIDENCE: analysis/eval.py:12]
Config lane: DR too easy. [EVIDENCE: summary.json hard ss_error 0.02]

## Discriminating probe (the proposed change)
[H1-PREDICTS] jitter drops below 0.02 within 500 iters
[H2-PREDICTS] jitter unchanged, ss_error worsens 20%
Change payload_radius 0.08 -> 0.05, all else identical.

## Status: pending approval
"""


def test_good_proposal_passes():
    res = lint_proposal(GOOD)
    assert res["ok"] is True and res["issues"] == []


def test_missing_h2_fails():
    res = lint_proposal(GOOD.replace("[H2-PREDICTS] jitter unchanged, ss_error worsens 20%\n", ""))
    assert res["ok"] is False
    assert any(i["rule"] == "h1h2-missing" for i in res["issues"])


def test_identical_predictions_fail():
    bad = GOOD.replace("[H2-PREDICTS] jitter unchanged, ss_error worsens 20%",
                       "[H2-PREDICTS] jitter drops below 0.02 within 500 iters")
    assert any(i["rule"] == "h1h2-identical" for i in lint_proposal(bad)["issues"])


def test_unevidenced_diagnosis_fails():
    bad = GOOD.replace("[EVIDENCE: analysis/eval.py:12]", "").replace(
        "[EVIDENCE: summary.json hard ss_error 0.02]", "")
    assert any(i["rule"] == "diagnosis-unevidenced" for i in lint_proposal(bad)["issues"])


def test_missing_analysis_ref_and_status():
    bad = GOOD.replace("diagnose-20260705-120000", "somewhere").replace(
        "next-20260705-130000", "x")
    assert any(i["rule"] == "no-analysis-ref" for i in lint_proposal(bad)["issues"])
    bad2 = GOOD.replace("## Status: pending approval\n", "")
    assert any(i["rule"] == "no-pending-approval" for i in lint_proposal(bad2)["issues"])


def test_probe_tokens_extracts_probe_section():
    toks = probe_tokens(GOOD)
    assert "payload_radius" in toks and "jitter" in toks
    assert "lane" not in toks  # diagnosis section text is excluded


def test_cli_proposal_lint(tmp_path, capsys):
    p = tmp_path / "next-20260705-130000.md"
    p.write_text(GOOD)
    assert main(["proposal-lint", "--path", str(p)]) == 0
    capsys.readouterr()
    p.write_text(GOOD.replace("[H1-PREDICTS]", "[HX]"))
    assert main(["proposal-lint", "--path", str(p)]) == 2


def test_cli_probe_novelty_reports_similar(tmp_path, capsys):
    d = tmp_path / "proposals"
    d.mkdir()
    (d / "next-20260101-000000.md").write_text(GOOD)
    p = d / "next-20260705-130000.md"
    p.write_text(GOOD)
    rc = main(["probe-novelty", "--root", str(tmp_path), "--proposal", str(p),
               "--proposals-dir", str(d)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["similar_proposals"] and out["similar_proposals"][0]["jaccard"] >= 0.3


def test_probe_novelty_path_alias(tmp_path, capsys):
    # M-6: --path is the canonical flag; --proposal stays a working alias.
    fp = tmp_path / "p.md"
    fp.write_text(GOOD)
    assert main(["probe-novelty", "--path", str(fp), "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["probe-novelty", "--root", str(tmp_path)]) == 2  # neither flag
    assert main(["probe-novelty", "--path", str(fp), "--proposal", str(fp),
                 "--root", str(tmp_path)]) == 2  # both flags
