"""R3 handler unit tests — load hooks/handlers.py directly (no omx_core needed
for route_emit; capture_flush/compact_breadcrumb/loop_gate tests build real
.omx roots via omx_core). Runner-level behavior (kill switches, timeout,
fail-open on garbage stdin) is covered by test_hook_runner.py."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HANDLERS_PATH = REPO / "hooks" / "handlers.py"
RUNNER = REPO / "hooks" / "run_hook.py"


def _load_handlers():
    spec = importlib.util.spec_from_file_location("omx_hook_handlers_r3", str(HANDLERS_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_hook(handler, payload, env_extra=None):
    import os
    env = dict(os.environ)
    env.pop("OMX_DISABLE", None)
    env.pop("OMX_SKIP_HOOKS", None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(RUNNER), handler],
        input=json.dumps(payload), capture_output=True, text=True, env=env,
        timeout=30)


# --- route_emit (spec 2.1) ---

def test_route_emit_shape():
    mod = _load_handlers()
    out = mod.route_emit({"prompt": "analyze this run"})
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "UserPromptSubmit"
    assert "<omx-routing>" in hso["additionalContext"]
    assert "STAGE(exp)" in hso["additionalContext"]


def test_route_emit_names_all_seven_stages():
    mod = _load_handlers()
    text = mod._ROUTE_CHECKPOINT
    for stage in ("exp-init", "exp-analyze", "exp-design", "exp-loop",
                  "wiki", "tree", "recipe"):
        assert stage in text


def test_route_emit_restates_the_three_non_negotiables():
    mod = _load_handlers()
    text = mod._ROUTE_CHECKPOINT
    assert "report-parse" in text          # never hand-parse reports
    assert "queue-launch" in text          # D4: queue only, never fire
    assert "experiments" in text           # results SSOT = experiments tree


def test_route_checkpoint_stays_under_2kib():
    # Routing context is paid on EVERY prompt in every project (spec 2.1).
    mod = _load_handlers()
    assert len(mod._ROUTE_CHECKPOINT.encode("utf-8")) <= 2048


def test_route_emit_registered_in_handlers_table():
    mod = _load_handlers()
    assert mod.HANDLERS["route_emit"] is mod.route_emit


def test_route_emit_through_runner():
    r = _run_hook("route_emit", {"prompt": "x"})
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
