"""v0.8.0: runs-on-disk vs campaigns drift — the July-2026 field condition."""

from omx_core.campaign import (
    adopt_drift,
    append_event,
    campaign_drift,
    init_campaign,
    read_ledger,
)
from omx_core.omx_paths import OmxPaths
from omx_core.tree import load_tree_schema

NOW = "2026-07-23T00:00:00+00:00"

# Minimal tree.yaml mirroring tree_fixtures.FLAT_TREE_YAML (test_tree_audit.py)
# but with one group level, so a run lands at experiments/<group>/<run_id>
# (D-R2-5: group = the run dir's parent segment). No `requires`/data_pointer
# needed — the run_id grammar clause alone detects the run.
_TREE_YAML = """\
version: 1
trees:
  index:
    root: experiments
    levels: [group]
run_id:
  grammar: "<label>[_<tag>]_<ts>"
  ts_format: "%y%m%d_%H%M%S"
  tag: optional
run_dir:
  eval_pattern: "eval/<mode>_<ts>"
  eval_modes: [static]
walk:
  ignore: ["legacy", "_*"]
"""


def _make_project(tmp_path, groups):
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    tree_yaml = prof / "tree.yaml"
    tree_yaml.write_text(_TREE_YAML, encoding="utf-8")
    for group, runs in groups.items():
        for run_id in runs:
            (tmp_path / "experiments" / group / run_id).mkdir(parents=True)
    paths = OmxPaths(root=tmp_path)
    schema = load_tree_schema(tree_yaml)
    return paths, schema, tmp_path


def test_drift_unregistered_group(tmp_path):
    paths, schema, base = _make_project(
        tmp_path, {"groupa": ["runa_tag_260722_120000"]})
    d = campaign_drift(paths, schema, base)
    assert d["ok"] is False
    assert d["unregistered"] == [{"group": "groupa", "runs": 1}]
    assert d["empty_ledger"] == []


def test_drift_empty_ledger(tmp_path):
    paths, schema, base = _make_project(
        tmp_path, {"groupa": ["runa_tag_260722_120000"]})
    init_campaign(paths, "groupa", now=NOW)
    d = campaign_drift(paths, schema, base)
    assert d["ok"] is False
    assert d["unregistered"] == []
    assert d["empty_ledger"] == [{"group": "groupa", "runs": 1}]


def test_drift_ok_when_ledger_has_events(tmp_path):
    paths, schema, base = _make_project(
        tmp_path, {"groupa": ["runa_tag_260722_120000"]})
    init_campaign(paths, "groupa", now=NOW)
    append_event(paths, "groupa", now=NOW, event="note", data={"k": "v"})
    d = campaign_drift(paths, schema, base)
    assert d["ok"] is True


def test_drift_ignores_campaign_without_runs(tmp_path):
    # a closed/historical campaign whose group left the tree is NOT drift
    paths, schema, base = _make_project(
        tmp_path, {"groupa": ["runa_tag_260722_120000"]})
    init_campaign(paths, "groupa", now=NOW)
    append_event(paths, "groupa", now=NOW, event="note", data={})
    init_campaign(paths, "old_campaign", now=NOW)
    d = campaign_drift(paths, schema, base)
    assert d["ok"] is True


def test_adopt_is_idempotent(tmp_path):
    paths, schema, base = _make_project(
        tmp_path, {"groupa": ["runa_tag_260722_120000"],
                   "groupb": ["runb_tag_260722_130000"]})
    init_campaign(paths, "groupa", now=NOW)  # exists but empty ledger
    res = adopt_drift(paths, schema, base, now=NOW)
    assert sorted(res["adopted"]) == ["groupa", "groupb"]
    assert campaign_drift(paths, schema, base)["ok"] is True
    assert read_ledger(paths, "groupa")[-1]["data"]["kind"] == "adopted"
    res2 = adopt_drift(paths, schema, base, now=NOW)
    assert res2["adopted"] == []
