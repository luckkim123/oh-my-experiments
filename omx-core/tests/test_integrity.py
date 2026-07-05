import json

from omx_core import integrity


def _mk_analysis(tmp_path, body="# r\n\ndata 1.0\n"):
    d = tmp_path / "run1" / "analysis" / "diagnose-20260705-120000"
    d.mkdir(parents=True)
    (d / "report.md").write_text(body)
    return d / "report.md"


def test_manifest_is_sibling(tmp_path):
    rp = _mk_analysis(tmp_path)
    assert integrity.manifest_path_for(rp) == rp.parent / "manifest.json"


def test_is_analysis_report(tmp_path):
    assert integrity.is_analysis_report(_mk_analysis(tmp_path)) is True
    loose = tmp_path / "report.md"
    loose.write_text("x")
    assert integrity.is_analysis_report(loose) is False


def test_stamp_then_verify_ok(tmp_path):
    rp = _mk_analysis(tmp_path)
    (rp.parent / "report.ko.md").write_text("# ko\n")
    integrity.stamp_report(rp, gates_passed=["coverage"], now="2026-07-05T12:00:00",
                           omx_version="0.2.0")
    m = json.loads((rp.parent / "manifest.json").read_text())
    assert m["integrity"]["gates_passed"] == ["coverage"]
    assert set(m["integrity"]["file_sha256"]) == {"report.md", "report.ko.md"}
    assert integrity.verify_report(rp)["status"] == "ok"
    assert integrity.verify_report(rp.parent)["status"] == "ok"  # dir form


def test_stamp_merges_existing_manifest(tmp_path):
    rp = _mk_analysis(tmp_path)
    (rp.parent / "manifest.json").write_text(json.dumps({"plots": ["a.png"]}))
    integrity.stamp_report(rp, gates_passed=["coverage"], now="2026-07-05T12:00:00",
                           omx_version=None)
    m = json.loads((rp.parent / "manifest.json").read_text())
    assert m["plots"] == ["a.png"] and "integrity" in m


def test_verify_detects_tamper(tmp_path):
    rp = _mk_analysis(tmp_path)
    integrity.stamp_report(rp, gates_passed=["coverage"], now="t", omx_version=None)
    rp.write_text("# tampered\n")
    v = integrity.verify_report(rp)
    assert v["status"] == "mismatch" and v["mismatched"] == ["report.md"]


def test_verify_unstamped_and_no_gates(tmp_path):
    rp = _mk_analysis(tmp_path)
    assert integrity.verify_report(rp)["status"] == "unstamped"
    integrity.stamp_report(rp, gates_passed=[], now="t", omx_version=None)
    assert integrity.verify_report(rp)["status"] == "no-gates"


def test_coverage_cli_stamps_on_ok(tmp_path, capsys):
    from omx_core.cli import main
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "metrics.yaml").write_text("output_root: experiments\n")  # no groups/markers -> vacuous pass
    rp = _mk_analysis(tmp_path)
    rc = main(["report-coverage", "--path", str(rp), "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["stamped"] is True
    assert (rp.parent / "manifest.json").exists()


def test_coverage_cli_skips_stamp_outside_analysis_tree(tmp_path, capsys):
    from omx_core.cli import main
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "metrics.yaml").write_text("output_root: experiments\n")
    rp = tmp_path / "report.md"
    rp.write_text("# loose copy\n")
    rc = main(["report-coverage", "--path", str(rp), "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["stamped"] is False
    assert not (tmp_path / "manifest.json").exists()
