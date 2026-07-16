"""_fetch_open_backlog unit tests (v0.7.2) — the route_emit backlog pre-fetch
added for the 2026-07-15 stranded-instruction incident shipped without tests;
these pin its formatting, fail-open paths, and the SIGALRM budget arithmetic
(2 sequential subprocess calls must fit inside run_hook's 3s default ceiling).
Loads hooks/handlers.py directly, same pattern as test_hook_handlers_r3.py."""
import importlib.util
import json
import subprocess
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HANDLERS_PATH = REPO / "hooks" / "handlers.py"
RUNNER_PATH = REPO / "hooks" / "run_hook.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_handlers():
    return _load(HANDLERS_PATH, "omx_hook_handlers_backlog")


def _fake_run(payload_by_status, returncode=0):
    def run(cmd, **kwargs):
        status = cmd[cmd.index("--status") + 1]
        return types.SimpleNamespace(
            returncode=returncode,
            stdout=json.dumps({"pages": payload_by_status.get(status, [])}),
            stderr="")
    return run


def test_backlog_happy_path_formats_both_statuses(monkeypatch):
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_omx_root", lambda p: "/fake/root")
    monkeypatch.setattr(subprocess, "run", _fake_run({
        "needs-experiment": [{"slug": "lead_a.md", "blocked_on": None}],
        "needs-apply-before-retrain": [{"slug": "gate_b.md", "blocked_on": "m4 remeasure"}],
    }))
    out = mod._fetch_open_backlog({"cwd": "/fake/root"})
    assert "<omx-open-backlog>" in out and "</omx-open-backlog>" in out
    assert "[needs-experiment] lead_a.md (blocked: unblocked)" in out
    assert "[needs-apply-before-retrain] gate_b.md (blocked: m4 remeasure)" in out


def test_backlog_empty_pages_returns_empty(monkeypatch):
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_omx_root", lambda p: "/fake/root")
    monkeypatch.setattr(subprocess, "run", _fake_run({}))
    assert mod._fetch_open_backlog({"cwd": "/fake/root"}) == ""


def test_backlog_nonzero_rc_fail_open(monkeypatch):
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_omx_root", lambda p: "/fake/root")
    monkeypatch.setattr(subprocess, "run", _fake_run(
        {"needs-experiment": [{"slug": "x.md"}]}, returncode=2))
    assert mod._fetch_open_backlog({"cwd": "/fake/root"}) == ""


def test_backlog_subprocess_timeout_fail_open(monkeypatch):
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_omx_root", lambda p: "/fake/root")

    def boom(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 0))
    monkeypatch.setattr(subprocess, "run", boom)
    assert mod._fetch_open_backlog({"cwd": "/fake/root"}) == ""


def test_backlog_no_omx_root_fail_open():
    mod = _load_handlers()
    # /  has no .omx anchor: _omx_root raises inside, fetch degrades to ""
    assert mod._fetch_open_backlog({"cwd": "/"}) == ""


def test_backlog_fetch_fits_sigalrm_budget():
    """Two sequential fetches must complete inside run_hook's ceiling for
    route_emit (default budget — route_emit is deliberately NOT in _BUDGETS)."""
    mod = _load_handlers()
    runner = _load(RUNNER_PATH, "omx_hook_runner_backlog")
    assert "route_emit" not in runner._BUDGETS
    assert 2 * mod._BACKLOG_FETCH_TIMEOUT_S < runner._TIMEOUT_S


def test_route_emit_appends_backlog_when_present(monkeypatch):
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_fetch_open_backlog", lambda p: "<omx-open-backlog>X</omx-open-backlog>")
    ctx = mod.route_emit({"prompt": "next experiment?"})["hookSpecificOutput"]["additionalContext"]
    assert ctx.endswith("<omx-open-backlog>X</omx-open-backlog>")
    assert "<omx-routing>" in ctx


def test_route_emit_plain_when_backlog_empty(monkeypatch):
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_fetch_open_backlog", lambda p: "")
    ctx = mod.route_emit({"prompt": "hi"})["hookSpecificOutput"]["additionalContext"]
    assert ctx == mod._ROUTE_CHECKPOINT
