"""T12: campaign plan semantics (D-R4-10). plan.json gains a `planned` list
(intent); campaign_status derives per-proposal status at read time by joining
against ledger events. Intent and outcome have different owners — status is
never duplicated into plan.json."""
import json

import pytest

from omx_core.campaign import (campaign_status, init_campaign, plan_add)
from omx_core.omx_paths import OmxError, OmxPaths

NOW = "2026-07-11T10:00:00"


def _p(tmp_path):
    return OmxPaths(root=str(tmp_path))


def _init(tmp_path):
    p = _p(tmp_path)
    init_campaign(p, "camp1", now=NOW, goal="reduce error")
    return p


def test_init_writes_plan_atomically(tmp_path):
    # regression: init_campaign used a bare write_text (campaign.py:35); after
    # T12 it is atomic (a .tmp sibling then os.replace). We can only observe the
    # RESULT (a valid plan.json), so assert it parses and has no leftover .tmp.
    p = _init(tmp_path)
    plan = json.loads(p.campaign_plan("camp1").read_text())
    assert plan["campaign_id"] == "camp1"
    assert not (p.campaign_dir("camp1") / "plan.json.tmp").exists()


def test_plan_add_appends_planned(tmp_path):
    p = _init(tmp_path)
    plan_add(p, "camp1", proposal_id="20260711-100000-a", summary="probe A", now=NOW)
    plan = json.loads(p.campaign_plan("camp1").read_text())
    assert plan["planned"][0]["proposal_id"] == "20260711-100000-a"
    assert plan["planned"][0]["summary"] == "probe A"
    assert plan["planned"][0]["added_at"] == NOW


def test_plan_add_dup_proposal_loud_fails(tmp_path):
    p = _init(tmp_path)
    plan_add(p, "camp1", proposal_id="20260711-100000-a", summary="x", now=NOW)
    with pytest.raises(OmxError):
        plan_add(p, "camp1", proposal_id="20260711-100000-a", summary="y", now=NOW)


def test_plan_add_is_atomic(tmp_path):
    p = _init(tmp_path)
    plan_add(p, "camp1", proposal_id="20260711-100000-a", summary="x", now=NOW)
    assert not (p.campaign_dir("camp1") / "plan.json.tmp").exists()


def test_status_reconciles_planned_against_ledger(tmp_path):
    from omx_core.campaign import append_event
    p = _init(tmp_path)
    plan_add(p, "camp1", proposal_id="p-planned", summary="only planned", now=NOW)
    plan_add(p, "camp1", proposal_id="p-kept", summary="was kept", now=NOW)
    plan_add(p, "camp1", proposal_id="p-discarded", summary="was discarded", now=NOW)
    # ledger events reference proposals via data.proposal / data.proposal_id
    append_event(p, "camp1", now=NOW, event="kept", run_id="r1",
                 data={"proposal": "p-kept"})
    append_event(p, "camp1", now=NOW, event="discarded", run_id="r2",
                 data={"proposal_id": "p-discarded"})
    status = campaign_status(p, "camp1")
    by_id = {e["proposal_id"]: e for e in status["plan"]}
    assert by_id["p-planned"]["derived_status"] == "planned"
    assert by_id["p-kept"]["derived_status"] == "kept"
    assert by_id["p-discarded"]["derived_status"] == "discarded"


def test_status_no_planned_key_is_empty_list(tmp_path):
    # a campaign created before any plan-add has no `planned` -> plan == []
    p = _init(tmp_path)
    status = campaign_status(p, "camp1")
    assert status["plan"] == []


def test_cli_campaign_plan_add(tmp_path, capsys):
    from omx_core import cli
    cli.main(["campaign-init", "--root", str(tmp_path), "--id", "camp1"])
    capsys.readouterr()
    rc = cli.main(["campaign-plan-add", "--root", str(tmp_path), "--id", "camp1",
                   "--proposal-id", "20260711-100000-a", "--summary", "probe A"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["planned"][-1]["proposal_id"] == "20260711-100000-a"


def test_cli_campaign_plan_add_dup_rc2(tmp_path, capsys):
    from omx_core import cli
    cli.main(["campaign-init", "--root", str(tmp_path), "--id", "camp1"])
    cli.main(["campaign-plan-add", "--root", str(tmp_path), "--id", "camp1",
              "--proposal-id", "p-a"])
    capsys.readouterr()
    rc = cli.main(["campaign-plan-add", "--root", str(tmp_path), "--id", "camp1",
                   "--proposal-id", "p-a"])
    assert rc == 2
