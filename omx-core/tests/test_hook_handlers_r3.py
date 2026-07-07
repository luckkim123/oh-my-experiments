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


# --- capture_flush (spec 2.2) ---

def _stamped_report_root(tmp_path):
    """Reuse the T3/T4 fixture chain to produce a root with a pending ledger."""
    from omx_core import cli
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "metrics.yaml").write_text(
        "diagnostic_groups:\n  core:\n    - reward\nengine_markers:\n  - ENGINE-OK\n",
        encoding="utf-8")
    adir = (tmp_path / "experiments" / "rsl_rl" / "e2e" / "run1" / "analysis"
            / "diagnose-20260707-000000")
    adir.mkdir(parents=True)
    report = adir / "report.md"
    report.write_text(
        "# Report\n\n## core\n\nreward improved. ENGINE-OK\n\n"
        "[FINDING] reward improved by 2x\n"
        "[EVIDENCE: code-exec — summary.json reward 0.5 -> 1.0]\n"
        "[CONFIDENCE: HIGH]\n",
        encoding="utf-8")
    cli.main(["report-coverage", "--path", str(report), "--root", str(tmp_path)])
    return tmp_path


def test_capture_flush_flushes_ledger(tmp_path, capsys):
    root = _stamped_report_root(tmp_path)
    capsys.readouterr()
    mod = _load_handlers()
    out = mod.capture_flush({"cwd": str(root), "session_id": "whatever"})
    assert out is None  # SessionEnd output is ignored by the platform
    from omx_core.omx_paths import OmxPaths
    from omx_core.wiki.storage import list_pages, read_page
    paths = OmxPaths(root=str(root))
    assert paths.produced_reports_ledger().read_text() == ""
    pages = [read_page(paths, slug) for slug in list_pages(paths)]
    assert any(p.category == "session-log" for p in pages)


def test_capture_flush_empty_root_is_silent_none(tmp_path):
    mod = _load_handlers()
    assert mod.capture_flush({"cwd": str(tmp_path)}) is None


def test_capture_flush_fails_open_on_garbage_cwd():
    mod = _load_handlers()
    assert mod.capture_flush({"cwd": 12345}) is None


# --- compact_breadcrumb (spec 2.3) ---

def _omx_skeleton(tmp_path):
    (tmp_path / ".omx").mkdir()
    return tmp_path


def test_breadcrumb_ignores_non_compact_source(tmp_path):
    mod = _load_handlers()
    _omx_skeleton(tmp_path)
    assert mod.compact_breadcrumb({"cwd": str(tmp_path), "source": "startup"}) is None


def test_breadcrumb_empty_state_is_none(tmp_path):
    mod = _load_handlers()
    _omx_skeleton(tmp_path)
    assert mod.compact_breadcrumb({"cwd": str(tmp_path), "source": "compact"}) is None


def test_breadcrumb_lists_recent_notes_and_pending_launch(tmp_path):
    mod = _load_handlers()
    root = _omx_skeleton(tmp_path)
    notes = root / ".omx" / "scratch" / "s-20260707-abc" / "notes.md"
    notes.parent.mkdir(parents=True)
    notes.write_text("breadcrumb", encoding="utf-8")
    pl = root / ".omx" / "runs" / "run1" / "pending-launch.json"
    pl.parent.mkdir(parents=True)
    pl.write_text("{}", encoding="utf-8")
    out = mod.compact_breadcrumb({"cwd": str(root), "source": "compact"})
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    ctx = hso["additionalContext"]
    assert "<omx-durable-state>" in ctx
    assert str(notes) in ctx
    assert "run1" in ctx


def test_breadcrumb_stale_notes_excluded(tmp_path):
    import os
    import time
    mod = _load_handlers()
    root = _omx_skeleton(tmp_path)
    notes = root / ".omx" / "scratch" / "s-20260101-old" / "notes.md"
    notes.parent.mkdir(parents=True)
    notes.write_text("old", encoding="utf-8")
    old = time.time() - 49 * 3600  # past the 48h window
    os.utime(notes, (old, old))
    assert mod.compact_breadcrumb({"cwd": str(root), "source": "compact"}) is None


def test_breadcrumb_reports_armed_loop(tmp_path):
    mod = _load_handlers()
    root = _omx_skeleton(tmp_path)
    from omx_core.omx_paths import OmxPaths
    from omx_core.state import load_state, save_state
    paths = OmxPaths(root=str(root))
    state = load_state(paths)
    state["active_loop"] = {"run_id": "run9", "deadline": "2026-07-08T00:00:00+00:00",
                            "iteration": 3, "hard_cap": 50, "armed_at": "x",
                            "adopted_session": None}
    save_state(paths, state)
    out = mod.compact_breadcrumb({"cwd": str(root), "source": "compact"})
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "run9" in ctx and "armed" in ctx
