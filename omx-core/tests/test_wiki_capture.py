"""Tests for `omx wiki capture-session` (#11, spec 3.7)."""
import json

from omx_core.cli import main

REPORT = """# r
[FINDING] cost dropped 0.5 -> 0.2 after the clamp fix
[EVIDENCE: summary.json ss_error none]
[CONFIDENCE: HIGH]

[FINDING] jitter unchanged at 0.03
[EVIDENCE: plots/jitter__trajectory.png]
[CONFIDENCE: MED]
"""


def _write_report(tmp_path):
    rp = tmp_path / "report.md"
    rp.write_text(REPORT)
    return rp


def _anchor(root):
    (root / ".hq").mkdir(exist_ok=True)
    (root / ".hq" / ".anchor").write_text("id: test-anchor\n")
    (root / ".git").mkdir(exist_ok=True)     # git anchor -> edit, not supersede


def test_capture_writes_stub_posts(tmp_path, capsys, live_hq):
    rp = _write_report(tmp_path)
    _anchor(tmp_path)
    rc = main(["wiki", "capture-session", "--root", str(tmp_path),
               "--from-report", str(rp), "--run-id", "run_a"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["captured"] == 2 and len(out["slugs"]) == 2
    from omx_core.wiki.hq_backend import read_post
    post = read_post(tmp_path, out["slugs"][0])
    fields = post["fields"]
    assert fields["topic"] == "session-log" and fields["confidence"] == "low"
    assert "auto-captured" in fields["keywords"] and "run_a" in fields["keywords"]
    assert "[EVIDENCE:" in post["body"] and "source report:" in post["body"]


def test_capture_is_rerun_safe(tmp_path, capsys, live_hq):
    """INV-2 append-merge survives the move: the second run must merge into the
    same subject chain, not fork a second post per finding."""
    rp = _write_report(tmp_path)
    _anchor(tmp_path)
    main(["wiki", "capture-session", "--root", str(tmp_path), "--from-report", str(rp)])
    first = json.loads(capsys.readouterr().out)["slugs"]
    rc = main(["wiki", "capture-session", "--root", str(tmp_path), "--from-report", str(rp)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["captured"] == 2
    assert out["slugs"] == first          # merged, not forked


def test_capture_loud_fails_on_malformed(tmp_path, capsys):
    rp = tmp_path / "report.md"
    rp.write_text("[EVIDENCE: orphan]\n")
    rc = main(["wiki", "capture-session", "--root", str(tmp_path), "--from-report", str(rp)])
    assert rc == 2


def test_capture_loud_fails_on_tampered_report(tmp_path, capsys):
    # I-2: capture-session must sit behind the same integrity boundary as
    # report-parse — a stamped-then-mutated report must never seed the wiki.
    from omx_core import integrity
    rp = _write_report(tmp_path)
    integrity.stamp_report(rp, gates_passed=["coverage"], now="2026-07-06T00:00:00",
                           omx_version="0.2.0")
    rp.write_text(REPORT + "\ntampered byte\n")
    rc = main(["wiki", "capture-session", "--root", str(tmp_path), "--from-report", str(rp)])
    assert rc == 2


def test_flush_no_longer_captures_and_keeps_the_ledger(tmp_path, capsys):
    """SessionEnd auto-capture is off (r6 D2): it never fired on this machine --
    no `produced-reports.jsonl` has ever existed here and no auto-captured page
    was ever written -- and after B4 its target is the SHARED post store, so
    turning it on for the first time by accident is not a thing to do quietly.

    The ledger is deliberately NOT truncated: the disabled path has to be
    reversible without having discarded the evidence of what it would have done.
    """
    from omx_core.omx_paths import OmxPaths
    from omx_core.wiki import capture

    rp = _write_report(tmp_path)
    paths = OmxPaths(root=tmp_path)
    ledger = paths.produced_reports_ledger()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps({"report": str(rp)}) + "\n")

    res = capture.flush_produced_reports(paths, now="2026-05-31T10:00:00")
    assert res == {"captured": 0, "skipped": 1, "disabled": True}
    assert ledger.read_text().strip(), "the ledger must survive the disabled flush"
    assert not (tmp_path / ".hq" / "community" / "posts").exists()
