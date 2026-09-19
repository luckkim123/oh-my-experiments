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


def _registered_bindings():
    """(event, matcher, handler_name) triples exactly as plugin.json declares
    them. `matcher` is None when the block carries no "matcher" key at all
    (UserPromptSubmit/SessionEnd/Stop apply to every invocation of that
    event)."""
    plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))
    bindings = set()
    for event, entries in plugin.get("hooks", {}).items():
        for entry in entries:
            matcher = entry.get("matcher")
            for h in entry["hooks"]:
                bindings.add((event, matcher, h["args"][1]))
    return bindings


# Measured against .claude-plugin/plugin.json on 2026-09-19 (run-completion-
# gate round, task 7). Each row is one registered (event, matcher, handler)
# triple -- see task-7-report.md for how this was verified.
EXPECTED_BINDINGS = {
    ("PreToolUse", "Edit|Write", "report_guard"),
    ("PreToolUse", "Bash", "closure_guard"),
    ("UserPromptSubmit", None, "route_emit"),
    ("SessionEnd", None, "capture_flush"),
    ("SessionStart", "compact", "compact_breadcrumb"),
    ("SessionStart", "startup|resume", "completion_notice"),
    ("Stop", None, "loop_gate"),
}


def test_registration_bindings_pin_event_and_matcher():
    """test_every_registration_has_a_handler / test_every_handler_is_registered
    above compare bare NAME sets -- the loop that builds those names discards
    `event` and `matcher` entirely, so rebinding closure_guard's matcher from
    "Bash" to something else, or moving a handler to a different event
    (PreToolUse -> Stop, say), leaves the name sets identical and both tests
    stay green. Pin the full (event, matcher, handler) triple so either kind
    of silent rebinding fails here instead. Also guards the SessionStart
    array specifically: it must keep BOTH the pre-existing "compact" entry
    and the "startup|resume" entry added this round -- dropping either one
    changes the set without changing any handler name."""
    assert _registered_bindings() == EXPECTED_BINDINGS


def test_registered_handler_maps_to_function_of_the_same_name():
    """The two parity tests above only check that a NAME like "completion_notice"
    exists as a key in HANDLERS -- not which function it points to. A mutation
    that rebinds HANDLERS["completion_notice"] = compact_breadcrumb passes both
    of them, because the key set is unchanged. Assert every registered handler
    name maps to the module-level function of that same name in handlers.py."""
    spec = importlib.util.spec_from_file_location("omx_handlers_identity", str(HANDLERS_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name, func in mod.HANDLERS.items():
        expected = getattr(mod, name, None)
        assert func is expected, (
            f"HANDLERS[{name!r}] is {func!r}, not the {name} function defined "
            f"in handlers.py -- registration points at the wrong callable"
        )


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
