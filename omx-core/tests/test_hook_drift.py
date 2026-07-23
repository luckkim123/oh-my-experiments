"""_fetch_campaign_drift unit tests (v0.8.0 campaign liveness leg 3): pin the
route_emit conditional <omx-campaign-drift> block — zero-tax when healthy,
fail-open on any resolution/schema error including omx_core absence (poison-
import contract, cf. test_hook_registration.py), and its splice into
_assemble_route_context after the backlog block. Loads hooks/handlers.py
directly, same pattern as test_hook_backlog.py. Fixture mirrors
test_campaign_drift.py's _make_project (same tree.yaml text)."""
import importlib.util
import sys
from pathlib import Path

from omx_core.campaign import append_event, init_campaign
from omx_core.omx_paths import OmxPaths

REPO = Path(__file__).resolve().parents[2]
HANDLERS_PATH = REPO / "hooks" / "handlers.py"

NOW = "2026-07-23T00:00:00+00:00"

# Same minimal one-group tree.yaml as test_campaign_drift.py.
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


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_handlers():
    return _load(HANDLERS_PATH, "omx_hook_handlers_drift")


def _make_project(tmp_path, groups):
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    tree_yaml = prof / "tree.yaml"
    tree_yaml.write_text(_TREE_YAML, encoding="utf-8")
    for group, runs in groups.items():
        for run_id in runs:
            (tmp_path / "experiments" / group / run_id).mkdir(parents=True)
    return OmxPaths(root=tmp_path)


def test_drift_healthy_project_returns_empty(tmp_path, monkeypatch):
    paths = _make_project(tmp_path, {"groupa": ["runa_tag_260722_120000"]})
    init_campaign(paths, "groupa", now=NOW)
    append_event(paths, "groupa", now=NOW, event="note", data={"k": "v"})
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_resolve_backlog_root", lambda p: str(tmp_path))
    assert mod._fetch_campaign_drift({"cwd": str(tmp_path)}) == ""


def test_drift_unregistered_group_emits_block(tmp_path, monkeypatch):
    _make_project(tmp_path, {"groupa": ["runa_tag_260722_120000"]})
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_resolve_backlog_root", lambda p: str(tmp_path))
    out = mod._fetch_campaign_drift({"cwd": str(tmp_path)})
    assert "<omx-campaign-drift>" in out and "</omx-campaign-drift>" in out
    assert "groupa" in out
    assert "campaign-drift --adopt" in out


def test_drift_no_root_fail_open(monkeypatch):
    mod = _load_handlers()

    def boom(payload):
        raise ValueError("no omx root anchor")
    monkeypatch.setattr(mod, "_resolve_backlog_root", boom)
    assert mod._fetch_campaign_drift({"cwd": "/"}) == ""


def test_drift_tree_yaml_absent_fail_open(tmp_path, monkeypatch):
    (tmp_path / ".omx").mkdir()  # anchor exists, but no profile/tree.yaml
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_resolve_backlog_root", lambda p: str(tmp_path))
    assert mod._fetch_campaign_drift({"cwd": str(tmp_path)}) == ""


def test_drift_poison_import_fails_open_and_route_emit_still_works(tmp_path, monkeypatch):
    # Poison-import contract (test_hook_registration.py pattern): omx_core
    # entirely absent must not raise, and route_emit must keep working.
    monkeypatch.setitem(sys.modules, "omx_core", None)
    monkeypatch.setitem(sys.modules, "omx_core.campaign", None)
    monkeypatch.setitem(sys.modules, "omx_core.omx_paths", None)
    monkeypatch.setitem(sys.modules, "omx_core.tree", None)
    mod = _load_handlers()
    assert mod._fetch_campaign_drift({"cwd": str(tmp_path)}) == ""
    out = mod.route_emit({"prompt": "x"})
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"


def test_assemble_route_context_appends_drift_after_backlog(monkeypatch):
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_fetch_open_backlog",
                        lambda p: "<omx-open-backlog>X</omx-open-backlog>")
    monkeypatch.setattr(mod, "_fetch_campaign_drift",
                        lambda p: "<omx-campaign-drift>Y</omx-campaign-drift>")
    ctx = mod._assemble_route_context({"cwd": "/fake"})["hookSpecificOutput"]["additionalContext"]
    assert "<omx-open-backlog>X</omx-open-backlog>" in ctx
    assert ctx.endswith("<omx-campaign-drift>Y</omx-campaign-drift>")
    assert ctx.index("<omx-open-backlog>") < ctx.index("<omx-campaign-drift>")
