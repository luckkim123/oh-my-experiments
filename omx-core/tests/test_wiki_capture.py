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


def test_capture_writes_stub_pages(tmp_path, capsys):
    rp = _write_report(tmp_path)
    rc = main(["wiki", "capture-session", "--root", str(tmp_path),
               "--from-report", str(rp), "--run-id", "run_a"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["captured"] == 2 and len(out["slugs"]) == 2
    from omx_core.omx_paths import OmxPaths
    from omx_core.wiki import storage
    page = storage.read_page(OmxPaths(root=tmp_path), out["slugs"][0])
    assert page.category == "session-log" and page.confidence == "low"
    assert "auto-captured" in page.tags and "run_a" in page.tags
    assert "[EVIDENCE:" in page.content and "source report:" in page.content


def test_capture_is_rerun_safe(tmp_path, capsys):
    rp = _write_report(tmp_path)
    main(["wiki", "capture-session", "--root", str(tmp_path), "--from-report", str(rp)])
    capsys.readouterr()
    rc = main(["wiki", "capture-session", "--root", str(tmp_path), "--from-report", str(rp)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["captured"] == 2  # merged, not forked (INV-2 append-merge)


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
