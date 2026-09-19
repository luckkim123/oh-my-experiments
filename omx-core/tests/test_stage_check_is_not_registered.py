"""The inverse of test_hook_registration.py's parity check, for exactly one
handler: `stage_check` MUST stay absent from both `hooks/handlers.py::HANDLERS`
and `.claude-plugin/plugin.json`'s `Stop` array.

Why: task 8 (run-completion-gate round) built `stage_check`, a Stop gate that
was measured -- against the 17 real STAGE-declaring transcripts under
~/.claude/projects, not synthetic ones -- to block 8 of them, up to 100% of
their turns, on sessions doing substantial genuine work. The user's decision
was "ship it disarmed": keep the function and its tests (a future redesign
should not start from nothing), but never let it fire live. See the
DISARMED comment block above `stage_check` in hooks/handlers.py for the full
reasoning (the measurement, and the two structural reasons a wider verb list
cannot fix) before re-registering it.

This test exists so a re-registration is a DELIBERATE act -- someone reads
that comment, decides it no longer applies, and edits both this test and the
registration together -- rather than a "tidy up this orphan handler" PR that
silently re-ships a gate already proven to trap real sessions."""
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / ".claude-plugin" / "plugin.json"
HANDLERS_PATH = REPO / "hooks" / "handlers.py"


def _load_handlers():
    spec = importlib.util.spec_from_file_location(
        "omx_stage_check_not_registered_handlers", str(HANDLERS_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _registered_handler_names():
    plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))
    names = set()
    for entries in plugin.get("hooks", {}).values():
        for entry in entries:
            for h in entry["hooks"]:
                names.add(h["args"][1])
    return names


def test_stage_check_is_still_implemented_but_not_registered():
    handlers = _load_handlers()
    # the function itself must still exist and be callable -- "disarmed",
    # not "deleted" (see DISARMED comment: kept for a future redesign).
    assert callable(handlers.stage_check)
    assert "stage_check" not in handlers.HANDLERS, (
        "stage_check is registered in HANDLERS -- this was disarmed on "
        "purpose (see the DISARMED comment above stage_check in "
        "hooks/handlers.py); re-registering is a deliberate decision, not "
        "a cleanup, so update this test alongside the registration.")
    assert "stage_check" not in _registered_handler_names(), (
        "stage_check is registered in plugin.json's Stop array -- this was "
        "disarmed on purpose (see the DISARMED comment above stage_check in "
        "hooks/handlers.py); re-registering is a deliberate decision, not "
        "a cleanup, so update this test alongside the registration.")
