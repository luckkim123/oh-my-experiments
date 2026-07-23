"""v0.9.0 program layer: cross-campaign artifact + aggregate view."""
import json

import pytest
from omx_core.campaign import (
    CampaignError,
    init_campaign,
    init_program,
    list_programs,
    plan_add,
    program_status,
)
from omx_core.omx_paths import OmxPaths

NOW = "2026-07-23T00:00:00+00:00"


@pytest.fixture
def paths(tmp_path):
    return OmxPaths(root=tmp_path)


def _campaigns(paths, ids):
    for c in ids:
        init_campaign(paths, c, now=NOW)


def test_init_program_writes_header(paths):
    _campaigns(paths, ["grp_a", "grp_b"])
    h = init_program(paths, "teacher-final-closeout", ["grp_a", "grp_b"], now=NOW)
    assert h == {"program_id": "teacher-final-closeout",
                 "campaigns": ["grp_a", "grp_b"],
                 "status": "active", "created": NOW}
    on_disk = json.loads(paths.program_json("teacher-final-closeout").read_text())
    assert on_disk == h
    assert not paths.program_plan_md("teacher-final-closeout").is_file()


def test_init_program_refuses_duplicate(paths):
    _campaigns(paths, ["grp_a"])
    init_program(paths, "prog", ["grp_a"], now=NOW)
    with pytest.raises(CampaignError, match="already exists"):
        init_program(paths, "prog", ["grp_a"], now=NOW)


def test_init_program_refuses_empty_members(paths):
    with pytest.raises(CampaignError, match="at least one"):
        init_program(paths, "prog", [], now=NOW)


def test_init_program_refuses_uninitialized_member(paths):
    _campaigns(paths, ["grp_a"])
    with pytest.raises(CampaignError, match="grp_missing"):
        init_program(paths, "prog", ["grp_a", "grp_missing"], now=NOW)


def test_list_programs(paths):
    assert list_programs(paths) == []
    _campaigns(paths, ["grp_a"])
    init_program(paths, "prog_b", ["grp_a"], now=NOW)
    init_program(paths, "prog_a", ["grp_a"], now=NOW)
    assert list_programs(paths) == ["prog_a", "prog_b"]


def test_program_status_aggregates_members(paths):
    _campaigns(paths, ["grp_a", "grp_b"])
    plan_add(paths, "grp_a", proposal_id="next-20260723-000000",
             summary="probe", now=NOW)
    init_program(paths, "prog", ["grp_a", "grp_b"], now=NOW)
    st = program_status(paths, "prog")
    assert st["program_id"] == "prog"
    assert st["status"] == "active"
    assert st["plan_md"] is False
    assert [c["campaign_id"] for c in st["campaigns"]] == ["grp_a", "grp_b"]
    assert st["campaigns"][0]["plan"][0]["derived_status"] == "planned"


def test_program_status_plan_md_flag(paths):
    _campaigns(paths, ["grp_a"])
    init_program(paths, "prog", ["grp_a"], now=NOW)
    paths.program_plan_md("prog").write_text("# plan\n")
    assert program_status(paths, "prog")["plan_md"] is True


def test_program_status_missing_member_becomes_error_entry(paths):
    import shutil
    _campaigns(paths, ["grp_a", "grp_b"])
    init_program(paths, "prog", ["grp_a", "grp_b"], now=NOW)
    shutil.rmtree(paths.campaign_dir("grp_b"))
    st = program_status(paths, "prog")
    assert st["campaigns"][0]["campaign_id"] == "grp_a"
    assert st["campaigns"][1]["campaign_id"] == "grp_b"
    assert "error" in st["campaigns"][1]


def test_program_status_default_id_resolution(paths):
    with pytest.raises(CampaignError, match="none"):
        program_status(paths)
    _campaigns(paths, ["grp_a"])
    init_program(paths, "only", ["grp_a"], now=NOW)
    assert program_status(paths)["program_id"] == "only"
    init_program(paths, "second", ["grp_a"], now=NOW)
    with pytest.raises(CampaignError, match="only"):
        program_status(paths)
