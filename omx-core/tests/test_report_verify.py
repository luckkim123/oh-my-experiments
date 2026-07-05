import json

from omx_core import integrity
from omx_core.cli import main

_REPORT = """# r

[FINDING] loss dropped 0.5 -> 0.2
[EVIDENCE: summary.json ss_error none]
[CONFIDENCE: HIGH]
"""


def _mk(tmp_path, stamped=True):
    d = tmp_path / "run1" / "analysis" / "diagnose-20260705-120000"
    d.mkdir(parents=True)
    rp = d / "report.md"
    rp.write_text(_REPORT)
    if stamped:
        integrity.stamp_report(rp, gates_passed=["coverage"], now="t", omx_version=None)
    return rp


def test_verify_ok(tmp_path, capsys):
    rp = _mk(tmp_path)
    rc = main(["report-verify", "--path", str(rp)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


def test_verify_strict_on_unstamped(tmp_path, capsys):
    rp = _mk(tmp_path, stamped=False)
    assert main(["report-verify", "--path", str(rp)]) == 2
    assert "unstamped" in capsys.readouterr().err


def test_verify_strict_on_tamper(tmp_path, capsys):
    rp = _mk(tmp_path)
    rp.write_text(_REPORT + "\nedited\n")
    assert main(["report-verify", "--path", str(rp)]) == 2


def test_parse_blocks_tampered_report(tmp_path, capsys):
    rp = _mk(tmp_path)
    rp.write_text(_REPORT + "\nedited\n")
    assert main(["report-parse", "--path", str(rp)]) == 2
    assert "mismatch" in capsys.readouterr().err


def test_parse_warns_but_reads_unstamped_legacy(tmp_path, capsys):
    rp = _mk(tmp_path, stamped=False)
    rc = main(["report-parse", "--path", str(rp)])
    cap = capsys.readouterr()
    assert rc == 0
    assert json.loads(cap.out)["n_findings"] == 1
    assert json.loads(cap.out)["integrity"] == "unstamped"
    assert "unstamped legacy" in cap.err


def test_parse_ok_on_stamped(tmp_path, capsys):
    rp = _mk(tmp_path)
    rc = main(["report-parse", "--path", str(rp)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["integrity"] == "ok"
