"""Task 11 — campaign ledger (#28, spec 2.9)."""
import json

from omx_core.cli import main


def test_init_log_status_round_trip(tmp_path, capsys):
    assert main(["campaign-init", "--root", str(tmp_path), "--id", "camp_a",
                 "--goal", "reduce ss_error"]) == 0
    capsys.readouterr()
    assert main(["campaign-log", "--root", str(tmp_path), "--id", "camp_a",
                 "--event", "launched", "--run", "alpha_t1_260601_120000"]) == 0
    assert main(["campaign-log", "--root", str(tmp_path), "--id", "camp_a",
                 "--event", "discarded", "--run", "alpha_t1_260601_120000",
                 "--data", '{"reason": "plateau"}']) == 0
    capsys.readouterr()
    assert main(["campaign-status", "--root", str(tmp_path), "--id", "camp_a"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["counts"] == {"launched": 1, "discarded": 1}
    assert out["runs"] == ["alpha_t1_260601_120000"]
    assert out["last"]["data"] == {"reason": "plateau"}
    ledger = (tmp_path / ".omx" / "campaigns" / "camp_a" / "ledger.jsonl").read_text()
    assert len(ledger.splitlines()) == 2               # append-only jsonl


def test_init_refuses_existing(tmp_path, capsys):
    assert main(["campaign-init", "--root", str(tmp_path), "--id", "camp_a"]) == 0
    capsys.readouterr()
    assert main(["campaign-init", "--root", str(tmp_path), "--id", "camp_a"]) == 2
    assert "already exists" in capsys.readouterr().err


def test_log_against_uninitialized_campaign_rc2(tmp_path, capsys):
    rc = main(["campaign-log", "--root", str(tmp_path), "--id", "ghost",
               "--event", "kept"])
    assert rc == 2
    assert "campaign-init" in capsys.readouterr().err  # explicit-init discipline


def test_malformed_data_rc2_never_silent(tmp_path, capsys):
    assert main(["campaign-init", "--root", str(tmp_path), "--id", "camp_a"]) == 0
    capsys.readouterr()
    assert main(["campaign-log", "--root", str(tmp_path), "--id", "camp_a",
                 "--event", "note", "--data", "not json"]) == 2
    assert main(["campaign-log", "--root", str(tmp_path), "--id", "camp_a",
                 "--event", "note", "--data", '["list"]']) == 2
    err = capsys.readouterr().err
    assert "JSON object" in err
    ledger = (tmp_path / ".omx" / "campaigns" / "camp_a" / "ledger.jsonl").read_text()
    assert ledger == ""                                # nothing was appended


def test_bad_event_and_bad_id_rc2(tmp_path, capsys):
    assert main(["campaign-init", "--root", str(tmp_path), "--id", "camp_a"]) == 0
    assert main(["campaign-log", "--root", str(tmp_path), "--id", "camp_a",
                 "--event", "exploded"]) == 2
    assert main(["campaign-init", "--root", str(tmp_path), "--id", "bad/seg"]) == 2


def test_list_campaigns(tmp_path, capsys):
    assert main(["campaign-init", "--root", str(tmp_path), "--id", "camp_a"]) == 0
    assert main(["campaign-init", "--root", str(tmp_path), "--id", "camp_b"]) == 0
    capsys.readouterr()
    assert main(["campaign-list", "--root", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [c["campaign_id"] for c in out["campaigns"]] == ["camp_a", "camp_b"]


def test_campaign_status_vanished_plan_loud_fails(tmp_path):
    # T11 (R2 final-review triage): a vanished plan.json must be OmxError
    # (rc2 via the CLI), never a raw FileNotFoundError traceback.
    import pytest
    from omx_core.campaign import campaign_status
    from omx_core.omx_paths import OmxError, OmxPaths
    paths = OmxPaths(root=str(tmp_path))
    # create a minimal campaign the way this test file's other tests do
    # (reuse the module-level helper/fixture); then remove the plan:
    cdir = paths.campaign_dir("camp1")
    cdir.mkdir(parents=True)
    (cdir / "plan.json").write_text("{}", encoding="utf-8")
    (cdir / "ledger.jsonl").write_text("", encoding="utf-8")
    (cdir / "plan.json").unlink()
    with pytest.raises(OmxError, match="plan.json"):
        campaign_status(paths, "camp1")
