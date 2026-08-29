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
    lines = [json.loads(ln) for ln in ledger.read_text().splitlines()]
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


# --- T4: flush_produced_reports, now DISABLED (r6 D2) ---
#
# The rescue path used to capture every stamped report into a session-log stub
# and truncate the ledger. That write now lands in the SHARED hq post store, so
# it was turned off deliberately rather than pointed at the new target: measured
# on this machine, no `produced-reports.jsonl` has ever existed and no
# auto-captured page was ever written, so the capability has never fired once --
# and building a flood guard, or a staging layer, for a code path with zero
# observed invocations is speculative work.
#
# The integrity/dedupe/torn-line tests went with the loop they were testing.
# What replaces them is the contract of the disabled path: it writes nothing,
# it truncates nothing, and it says so.

def _stamped_report_with_ledger(tmp_path) -> Path:
    """Build a stamped analysis report AND its ledger entry via the real verbs."""
    from omx_core import cli
    _write_minimal_profile(tmp_path)
    report = _write_analysis_report(tmp_path)
    cli.main(["report-coverage", "--path", str(report), "--root", str(tmp_path)])
    return report


def test_flush_writes_nothing_and_keeps_the_ledger(tmp_path, capsys):
    from omx_core.wiki.capture import flush_produced_reports
    _stamped_report_with_ledger(tmp_path)
    capsys.readouterr()
    paths = OmxPaths(root=str(tmp_path))
    before = paths.produced_reports_ledger().read_text()
    res = flush_produced_reports(paths, now="2026-07-07T12:00:00")
    assert res == {"captured": 0, "skipped": 1, "disabled": True}
    # Not truncated: the disabled path must stay reversible without having
    # thrown away the record of what it would have captured.
    assert paths.produced_reports_ledger().read_text() == before
    assert not (tmp_path / ".hq" / "community" / "posts").exists()


def test_flush_says_disabled_rather_than_reporting_a_quiet_zero(tmp_path):
    """`{"captured": 0}` alone is indistinguishable from "nothing to do", and
    this repo has lost three tools to reading a zero as an absence. The flag is
    the difference between "off" and "empty"."""
    from omx_core.wiki.capture import flush_produced_reports
    res = flush_produced_reports(OmxPaths(root=str(tmp_path)), now="2026-07-07T12:00:00")
    assert res == {"captured": 0, "skipped": 0, "disabled": True}


def test_flush_counts_what_it_did_not_capture(tmp_path, capsys):
    """The pending count is the whole reason to keep reading the ledger: it is
    how anyone finds out the disabled path has a backlog."""
    from omx_core.wiki.capture import flush_produced_reports
    report = _stamped_report_with_ledger(tmp_path)
    from omx_core import cli
    cli.main(["report-coverage", "--path", str(report), "--root", str(tmp_path)])
    capsys.readouterr()
    paths = OmxPaths(root=str(tmp_path))
    assert len(paths.produced_reports_ledger().read_text().splitlines()) == 2
    assert flush_produced_reports(paths, now="2026-07-07T12:00:00")["skipped"] == 2


def test_cli_capture_flush_verb(tmp_path, capsys):
    from omx_core import cli
    _stamped_report_with_ledger(tmp_path)
    capsys.readouterr()
    rc = cli.main(["wiki", "capture-flush", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out == {"captured": 0, "skipped": 1, "disabled": True}
