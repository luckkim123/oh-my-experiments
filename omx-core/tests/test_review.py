import json

from omx_core.review import review_report
from omx_core.cli import main

GOOD = """# r
## TL;DR
ok 1.2

## constraints
value moved 0.5 -> 0.2 at iter 800

[FINDING] cost dropped 0.5 -> 0.2
[EVIDENCE: analysis/eval.py:12 summary.json]
[CONFIDENCE: HIGH]

## verdict
fine 0.2
"""


def test_clean_report_approves():
    r = review_report(GOOD)
    assert r["verdict"] == "approve" and r["findings"] == []


def test_no_findings_is_major():
    r = review_report("# r\n\nprose only 1 2 3\n")
    assert r["verdict"] == "revise"
    assert any(f["issue"] == "no-findings" for f in r["findings"])


def test_high_conf_png_only_is_major():
    text = GOOD.replace("[EVIDENCE: analysis/eval.py:12 summary.json]",
                        "[EVIDENCE: plots/loss__trajectory.png]")
    r = review_report(text)
    assert any(f["issue"] == "high-conf-plot-only" and f["severity"] == "major"
               for f in r["findings"])


def test_wall_of_text_is_minor():
    wall = " ".join(["word"] * 130)
    r = review_report(GOOD + "\n## discussion\n\n" + wall + "\n")
    kinds = {f["issue"] for f in r["findings"]}
    assert "wall-of-text" in kinds


def test_empty_shell_section_is_minor():
    r = review_report(GOOD + "\n## generalization\n\nno numbers here at all\n")
    assert any(f["issue"] == "empty-shell-section" for f in r["findings"])


def test_depth_regression_is_major():
    shrunk = GOOD.replace("[FINDING] cost dropped 0.5 -> 0.2\n[EVIDENCE: analysis/eval.py:12 summary.json]\n[CONFIDENCE: HIGH]\n", "")
    r = review_report(shrunk, baseline_text=GOOD)
    assert r["verdict"] == "revise"
    assert any(f["issue"] == "depth-regression" for f in r["findings"])


def test_cli_records_review(tmp_path, capsys):
    d = tmp_path / "run1" / "analysis" / "diagnose-20260705-120000"
    d.mkdir(parents=True)
    rp = d / "report.md"
    rp.write_text(GOOD)
    rc = main(["report-review", "--path", str(rp), "--record-to", str(d)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "approve"
    assert json.loads((d / "review.json").read_text())["verdict"] == "approve"
