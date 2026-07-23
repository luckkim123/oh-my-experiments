"""v0.8.0 campaign liveness: byproduct writers + label/predecessor fields."""
import json

import pytest
from omx_core.campaign import (
    EVENTS,
    campaign_status,
    init_campaign,
    list_campaigns,
    plan_add,
    read_ledger,
    record_analyzed,
    record_launched,
)
from omx_core.omx_paths import OmxPaths

NOW = "2026-07-23T00:00:00+00:00"


@pytest.fixture
def paths(tmp_path):
    return OmxPaths(root=tmp_path)


def _report(tmp_path, group="groupa", run="runa_tag_260722_120000",
            analysis="diagnose-20260722-120000"):
    d = tmp_path / "experiments" / group / run / "analysis" / analysis
    d.mkdir(parents=True)
    fp = d / "report.md"
    fp.write_text("# r\n")
    return fp


def test_analyzed_in_events():
    assert "analyzed" in EVENTS


def test_record_analyzed_auto_inits_and_appends(paths, tmp_path):
    fp = _report(tmp_path)
    res = record_analyzed(paths, fp, now=NOW)
    assert res["status"] == "logged"
    assert res["campaign_id"] == "groupa"
    plan = json.loads(paths.campaign_plan("groupa").read_text())
    assert plan["auto_initialized"] is True
    events = read_ledger(paths, "groupa")
    assert len(events) == 1
    assert events[0]["event"] == "analyzed"
    assert events[0]["run_id"] == "runa_tag_260722_120000"
    assert events[0]["data"]["report"] == str(fp.resolve())


def test_record_analyzed_dedups_same_report(paths, tmp_path):
    fp = _report(tmp_path)
    record_analyzed(paths, fp, now=NOW)
    res = record_analyzed(paths, fp, now=NOW)
    assert res["status"] == "duplicate"
    assert len(read_ledger(paths, "groupa")) == 1


def test_record_analyzed_existing_campaign_not_reinited(paths, tmp_path):
    init_campaign(paths, "groupa", now=NOW, goal="g")
    fp = _report(tmp_path)
    res = record_analyzed(paths, fp, now=NOW)
    assert res["status"] == "logged"
    plan = json.loads(paths.campaign_plan("groupa").read_text())
    assert plan["goal"] == "g"
    assert "auto_initialized" not in plan


def test_record_launched_joins_planning_campaign(paths):
    init_campaign(paths, "groupa", now=NOW)
    plan_add(paths, "groupa", proposal_id="next-20260723-000001",
             summary="probe", now=NOW)
    res = record_launched(paths, "next-20260723-000001",
                          "runb_tag_260723_010101", now=NOW)
    assert res["status"] == "logged"
    assert res["campaign_id"] == "groupa"
    ev = read_ledger(paths, "groupa")[-1]
    assert ev["event"] == "launched"
    assert ev["run_id"] == "runb_tag_260723_010101"
    assert ev["data"]["proposal_id"] == "next-20260723-000001"
    # the join settles derived_status
    st = campaign_status(paths, "groupa")
    assert st["plan"][0]["derived_status"] == "launched"


def test_record_launched_cross_group(paths):
    # proposal planned in campaign A; run lands in (unrelated) group B —
    # the event must go to A, the planner, not B.
    init_campaign(paths, "groupa", now=NOW)
    plan_add(paths, "groupa", proposal_id="p1", now=NOW)
    res = record_launched(paths, "p1", "runc_tag_260723_020202", now=NOW)
    assert res["campaign_id"] == "groupa"


def test_record_launched_dedup_and_unplanned(paths):
    init_campaign(paths, "groupa", now=NOW)
    plan_add(paths, "groupa", proposal_id="p1", now=NOW)
    record_launched(paths, "p1", "runc_tag_260723_020202", now=NOW)
    assert record_launched(paths, "p1", "runc_tag_260723_020202",
                           now=NOW)["status"] == "duplicate"
    assert len(read_ledger(paths, "groupa")) == 1
    assert record_launched(paths, "nope", "rund_tag_260723_030303",
                           now=NOW)["status"] == "unplanned"


def test_plan_add_label_roundtrip(paths):
    init_campaign(paths, "groupa", now=NOW)
    plan_add(paths, "groupa", proposal_id="p1", summary="s", label="C2", now=NOW)
    st = campaign_status(paths, "groupa")
    assert st["plan"][0]["label"] == "C2"
    # old entries without label read as ""
    plan_add(paths, "groupa", proposal_id="p2", now=NOW)
    assert st is not None
    st2 = campaign_status(paths, "groupa")
    assert st2["plan"][1]["label"] == ""


def test_init_predecessor_surfaced(paths):
    init_campaign(paths, "old", now=NOW)
    init_campaign(paths, "new", now=NOW, predecessor="old")
    plan = json.loads(paths.campaign_plan("new").read_text())
    assert plan["predecessor"] == "old"
    listed = {c["campaign_id"]: c for c in list_campaigns(paths)}
    assert listed["new"]["predecessor"] == "old"
    assert "predecessor" not in listed["old"]
