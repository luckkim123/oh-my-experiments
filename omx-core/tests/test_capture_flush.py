"""T3+T4: produced-reports ledger write-site and the capture-flush rescue path
(spec 2.2). The ledger is root-level (.omx/state/produced-reports.jsonl) —
deliberately NOT under scratch/ (session-id-free, D-R3-5)."""
import json
from pathlib import Path

from omx_core.omx_paths import OmxPaths


def test_produced_reports_ledger_path(tmp_path):
    paths = OmxPaths(root=str(tmp_path))
    ledger = paths.produced_reports_ledger()
    assert ledger == tmp_path / ".omx" / "state" / "produced-reports.jsonl"


def _write_minimal_profile(root: Path):
    prof = root / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "metrics.yaml").write_text(
        "groups:\n  core:\n    - reward\nengine_markers:\n  - ENGINE-OK\n",
        encoding="utf-8")


def _write_analysis_report(root: Path) -> Path:
    # Analysis-tree shape: .../<run>/analysis/<analysis_id>/report.md so the
    # stamper recognizes it (integrity.is_analysis_report).
    adir = root / "experiments" / "rsl_rl" / "e2e" / "run1" / "analysis" / "diagnose-20260707-000000"
    adir.mkdir(parents=True)
    report = adir / "report.md"
    report.write_text(
        "# Report\n\n## core\n\nreward improved. ENGINE-OK\n\n"
        "[FINDING] reward improved by 2x\n"
        "[EVIDENCE: code-exec — summary.json reward 0.5 -> 1.0]\n"
        "[CONFIDENCE: HIGH]\n",
        encoding="utf-8")
    return report


def test_stamp_path_appends_ledger_line(tmp_path, capsys):
    from omx_core import cli
    _write_minimal_profile(tmp_path)
    report = _write_analysis_report(tmp_path)
    rc = cli.main(["report-coverage", "--path", str(report), "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["stamped"] is True
    ledger = OmxPaths(root=str(tmp_path)).produced_reports_ledger()
    lines = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert len(lines) == 1
    assert lines[0]["report"] == str(report.resolve())
    assert "stamped_at" in lines[0]


def test_unstamped_run_appends_nothing(tmp_path, capsys):
    # A coverage run that fails the gate (missing group) must not enter the
    # ledger. NB: cli.main() swallows SystemExit(str) and returns rc 2
    # (cli.py:1499) — assert on the return code, do not expect a raise.
    from omx_core import cli
    _write_minimal_profile(tmp_path)
    report = _write_analysis_report(tmp_path)
    report.write_text("# Report\n\nnothing relevant\n", encoding="utf-8")
    rc = cli.main(["report-coverage", "--path", str(report), "--root", str(tmp_path)])
    assert rc == 2
    assert not OmxPaths(root=str(tmp_path)).produced_reports_ledger().exists()


# --- T4: flush_produced_reports (spec 2.2) ---

def _stamped_report_with_ledger(tmp_path) -> Path:
    """Build a stamped analysis report AND its ledger entry via the real verbs."""
    from omx_core import cli
    _write_minimal_profile(tmp_path)
    report = _write_analysis_report(tmp_path)
    cli.main(["report-coverage", "--path", str(report), "--root", str(tmp_path)])
    return report


def test_flush_captures_and_truncates(tmp_path, capsys):
    from omx_core.wiki.capture import flush_produced_reports
    report = _stamped_report_with_ledger(tmp_path)
    capsys.readouterr()
    paths = OmxPaths(root=str(tmp_path))
    res = flush_produced_reports(paths, now="2026-07-07T12:00:00")
    assert res == {"captured": 1, "skipped": 0}
    # idempotent bookkeeping: ledger truncated after processing
    assert paths.produced_reports_ledger().read_text() == ""
    # a session-log stub page exists
    from omx_core.wiki.storage import list_pages, read_page
    pages = [read_page(paths, slug) for slug in list_pages(paths)]
    assert any(p.category == "session-log" for p in pages)


def test_flush_missing_report_skipped_not_fatal(tmp_path, capsys):
    from omx_core.wiki.capture import flush_produced_reports
    report = _stamped_report_with_ledger(tmp_path)
    capsys.readouterr()
    report.unlink()
    res = flush_produced_reports(OmxPaths(root=str(tmp_path)), now="2026-07-07T12:00:00")
    assert res == {"captured": 0, "skipped": 1}


def test_flush_dedupes_reports_across_lines(tmp_path, capsys):
    from omx_core import cli
    from omx_core.wiki.capture import flush_produced_reports
    report = _stamped_report_with_ledger(tmp_path)
    cli.main(["report-coverage", "--path", str(report), "--root", str(tmp_path)])  # 2nd stamp
    capsys.readouterr()
    paths = OmxPaths(root=str(tmp_path))
    assert len(paths.produced_reports_ledger().read_text().splitlines()) == 2
    res = flush_produced_reports(paths, now="2026-07-07T12:00:00")
    assert res == {"captured": 1, "skipped": 0}


def test_flush_torn_line_warns_and_continues(tmp_path, capsys):
    from omx_core.wiki.capture import flush_produced_reports
    _stamped_report_with_ledger(tmp_path)
    capsys.readouterr()
    paths = OmxPaths(root=str(tmp_path))
    with open(paths.produced_reports_ledger(), "a", encoding="utf-8") as fh:
        fh.write('{"report": "/torn')  # torn last line
    res = flush_produced_reports(paths, now="2026-07-07T12:00:00")
    assert res["captured"] == 1
    assert "unparseable" in capsys.readouterr().err


def test_flush_no_ledger_is_zero(tmp_path):
    from omx_core.wiki.capture import flush_produced_reports
    res = flush_produced_reports(OmxPaths(root=str(tmp_path)), now="2026-07-07T12:00:00")
    assert res == {"captured": 0, "skipped": 0}


def test_flush_tampered_report_skipped(tmp_path, capsys):
    # Post-stamp tamper -> integrity mismatch -> skip, never loud-fail (rescue path).
    from omx_core.wiki.capture import flush_produced_reports
    report = _stamped_report_with_ledger(tmp_path)
    capsys.readouterr()
    report.write_text(report.read_text() + "\ntampered\n", encoding="utf-8")
    res = flush_produced_reports(OmxPaths(root=str(tmp_path)), now="2026-07-07T12:00:00")
    assert res == {"captured": 0, "skipped": 1}
    assert "integrity" in capsys.readouterr().err


def test_cli_capture_flush_verb(tmp_path, capsys):
    from omx_core import cli
    _stamped_report_with_ledger(tmp_path)
    capsys.readouterr()
    rc = cli.main(["wiki", "capture-flush", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out == {"captured": 1, "skipped": 0}
