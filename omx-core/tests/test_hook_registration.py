"""Contract tests (spec 3): plugin.json hook registrations <-> handlers table
parity (both directions), and handlers.py importability without omx_core."""
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / ".claude-plugin" / "plugin.json"
HANDLERS_PATH = REPO / "hooks" / "handlers.py"

_RUNNER_BUILTINS = {"ping", "sleep"}  # test probes, never registered


def _registered_handler_names():
    plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))
    names = set()
    for event, entries in plugin.get("hooks", {}).items():
        for entry in entries:
            for h in entry["hooks"]:
                assert h["type"] == "command"
                assert h["command"] == "python3"
                assert h["args"][0] == "${CLAUDE_PLUGIN_ROOT}/hooks/run_hook.py"
                names.add(h["args"][1])
    return names


def _handler_table_names():
    spec = importlib.util.spec_from_file_location("omx_handlers_parity", str(HANDLERS_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return set(mod.HANDLERS)


def test_every_registration_has_a_handler():
    missing = _registered_handler_names() - _handler_table_names() - _RUNNER_BUILTINS
    assert not missing, f"plugin.json registers handlers that do not exist: {missing}"


def test_every_handler_is_registered():
    unregistered = _handler_table_names() - _registered_handler_names()
    assert not unregistered, f"handlers with no plugin.json registration: {unregistered}"


def test_handlers_import_without_omx_core(monkeypatch):
    # D9/version-resilience: hooks must work before `omx doctor` passes.
    # Poison the import so any module-level omx_core import would explode.
    monkeypatch.setitem(sys.modules, "omx_core", None)
    monkeypatch.setitem(sys.modules, "omx_core.omx_paths", None)
    spec = importlib.util.spec_from_file_location("omx_handlers_nocore", str(HANDLERS_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "route_emit" in mod.HANDLERS
    out = mod.route_emit({"prompt": "x"})
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
