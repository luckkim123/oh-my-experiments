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
        "[CONFIDENCE: high]\n",
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
