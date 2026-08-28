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
    # The skeletons are seeded so a plan starts with the sections program-lint
    # gates; whether they are FILLED is program-lint's question, not init's.
    plan = paths.program_plan_md("teacher-final-closeout").read_text()
    assert "## Objective" in plan
    assert "## Decisions for the user" in plan
    assert "## Predicted outcome" in plan
    handoff = (paths.program_dir("teacher-final-closeout") / "HANDOFF.md").read_text()
    assert "## Held decisions" in handoff


def test_init_program_never_overwrites_an_existing_plan(paths):
    """The git-mv migration path stays open: a narrative already in place wins."""
    _campaigns(paths, ["grp_a"])
    init_program(paths, "prog", ["grp_a"], now=NOW)
    paths.program_plan_md("prog").write_text("# hand-written\n")
    init_program(paths, "prog", [], now=NOW)
    assert paths.program_plan_md("prog").read_text() == "# hand-written\n"


def test_init_program_reinit_appends_and_preserves_created(paths):
    """Re-init is an append-only upsert (the attach-later path), not an error:
    new members are added, existing ones are never dropped or duplicated, and
    the original `created` stamp survives."""
    _campaigns(paths, ["grp_a", "grp_b"])
    init_program(paths, "prog", ["grp_a"], now=NOW)
    later = "2026-08-04T00:00:00+00:00"
    h = init_program(paths, "prog", ["grp_a", "grp_b"], now=later)
    assert h["campaigns"] == ["grp_a", "grp_b"]
    assert h["created"] == NOW
    assert json.loads(paths.program_json("prog").read_text()) == h


def test_init_program_allows_empty_members(paths):
    """A research line is planned before its first run exists — the program
    must open with zero members so PLAN.md has a home from day one."""
    h = init_program(paths, "prog", [], now=NOW)
    assert h["campaigns"] == []
    assert program_status(paths, "prog")["campaigns"] == []


def test_init_program_refuses_dir_without_program_json(paths):
    paths.program_dir("prog").mkdir(parents=True)
    with pytest.raises(CampaignError, match="already exists"):
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


# --- .hq/ cutover (team-lead Rule A): list_programs() reads BOTH stores -----

def _write_anchor(tmp_path, anchor_id="test-anchor"):
    """program_json() resolves via _write(), which short-circuits to legacy
    unconditionally without a parseable anchor (branch 1) — a state real
    .hq/ content never has, since only an anchored _write() puts content
    there. Every fixture below must anchor to be realistic."""
    f = tmp_path / ".hq" / ".anchor"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f"id: {anchor_id}\n", encoding="utf-8")


def test_list_programs_unions_legacy_and_new_new_wins_collision(paths, tmp_path):
    """Same three-way fixture as list_campaigns, but on the community/ layer
    programs_root() enumerates."""
    import json as _json

    _write_anchor(tmp_path)
    legacy_only = tmp_path / ".omx" / "programs" / "legacy_only"
    legacy_only.mkdir(parents=True)
    (legacy_only / "program.json").write_text(_json.dumps({"program_id": "legacy_only"}))

    new_only = tmp_path / ".hq" / "community" / "programs" / "new_only"
    new_only.mkdir(parents=True)
    # program.json for a NEW program lives under config/, not community/ —
    # this entry proves programs_root()'s union alone still finds it (its
    # PLAN.md/HANDOFF.md narrative half is what's actually here).
    (new_only / "PLAN.md").write_text("# plan\n")
    (tmp_path / ".hq" / "config" / "experiments" / "programs" / "new_only").mkdir(parents=True)
    (tmp_path / ".hq" / "config" / "experiments" / "programs" / "new_only" / "program.json"
     ).write_text(_json.dumps({"program_id": "new_only"}))

    both_legacy = tmp_path / ".omx" / "programs" / "both"
    both_legacy.mkdir(parents=True)
    (both_legacy / "program.json").write_text(_json.dumps({"program_id": "both", "src": "legacy"}))
    both_new_community = tmp_path / ".hq" / "community" / "programs" / "both"
    both_new_community.mkdir(parents=True)
    both_new_config = tmp_path / ".hq" / "config" / "experiments" / "programs" / "both"
    both_new_config.mkdir(parents=True)
    (both_new_config / "program.json").write_text(_json.dumps({"program_id": "both", "src": "new"}))

    assert list_programs(paths) == ["both", "legacy_only", "new_only"]


def test_list_programs_finds_config_layer_only_program(paths, tmp_path):
    """A program whose ONLY file anywhere is program.json under
    config/experiments/programs/<id>/ (no matching community/ entry at all)
    must still be found — team-lead's explicit 'check that case' directive."""
    import json as _json
    _write_anchor(tmp_path)
    config_only = tmp_path / ".hq" / "config" / "experiments" / "programs" / "config_only"
    config_only.mkdir(parents=True)
    (config_only / "program.json").write_text(_json.dumps({"program_id": "config_only"}))
    assert list_programs(paths) == ["config_only"]


def test_program_status_aggregates_members(paths):
    _campaigns(paths, ["grp_a", "grp_b"])
    plan_add(paths, "grp_a", proposal_id="next-20260723-000000",
             summary="probe", now=NOW)
    init_program(paths, "prog", ["grp_a", "grp_b"], now=NOW)
    st = program_status(paths, "prog")
    assert st["program_id"] == "prog"
    assert st["status"] == "active"
    # init seeds the skeleton, so plan_md reports existence; adequacy is program-lint's job
    assert st["plan_md"] is True
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
