"""_fetch_open_backlog unit tests (v0.7.2, re-contracted v0.7.3) — pin the
route_emit backlog pre-fetch: ONE unfiltered `omx wiki list` call filtered
locally (halved per-turn subprocess tax), formatting, the SIGALRM budget
arithmetic, and the two-tier degradation: no omx root -> '' (silent, correct
for non-omx projects) vs a FAILED fetch on a real omx root -> a visible WARN
block (2026-07-16 audit: json.loads inside a blanket except returned '' on any
non-JSON stdout, silently erasing the backlog — the stranded-instruction class).
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


def _fake_run(pages, returncode=0, stdout=None):
    def run(cmd, **kwargs):
        # v0.7.3: ONE unfiltered `omx wiki list` call; the hook filters by status
        # locally (halves the per-turn subprocess tax vs the two --status calls).
        assert "--status" not in cmd
        return types.SimpleNamespace(
            returncode=returncode,
            stdout=json.dumps({"pages": pages}) if stdout is None else stdout,
            stderr="")
    return run


def test_backlog_happy_path_formats_both_statuses(monkeypatch):
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_resolve_backlog_root", lambda p: "/fake/root")
    monkeypatch.setattr(subprocess, "run", _fake_run([
        {"slug": "gate_b.md", "status": "needs-apply-before-retrain", "blocked_on": "m4 remeasure"},
        {"slug": "lead_a.md", "status": "needs-experiment", "blocked_on": None},
        {"slug": "done.md", "status": "resolved", "blocked_on": None},
        {"slug": "plain.md", "status": None, "blocked_on": None},
    ]))
    out = mod._fetch_open_backlog({"cwd": "/fake/root"})
    assert "<omx-open-backlog>" in out and "</omx-open-backlog>" in out
    assert "[needs-experiment] lead_a.md (blocked: unblocked)" in out
    assert "[needs-apply-before-retrain] gate_b.md (blocked: m4 remeasure)" in out
    # non-actionable pages are filtered out; grouping stays needs-experiment first
    assert "done.md" not in out and "plain.md" not in out
    assert out.index("lead_a.md") < out.index("gate_b.md")


def test_backlog_empty_pages_returns_empty(monkeypatch):
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_resolve_backlog_root", lambda p: "/fake/root")
    monkeypatch.setattr(subprocess, "run", _fake_run([]))
    assert mod._fetch_open_backlog({"cwd": "/fake/root"}) == ""


def test_backlog_nonzero_rc_emits_visible_warning(monkeypatch):
    # A FAILED fetch on a real omx root must degrade VISIBLY, not to "" — a
    # silently dropped backlog re-arms the 2026-07-15 stranded-instruction
    # incident (open leads exist but vanish with zero signal).
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_resolve_backlog_root", lambda p: "/fake/root")
    monkeypatch.setattr(subprocess, "run", _fake_run(
        [{"slug": "x.md", "status": "needs-experiment"}], returncode=2))
    out = mod._fetch_open_backlog({"cwd": "/fake/root"})
    assert "<omx-open-backlog>" in out and "WARN" in out
    assert "omx wiki list --status needs-experiment" in out   # manual fallback command


def test_backlog_subprocess_timeout_emits_visible_warning(monkeypatch):
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_resolve_backlog_root", lambda p: "/fake/root")

    def boom(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 0))
    monkeypatch.setattr(subprocess, "run", boom)
    out = mod._fetch_open_backlog({"cwd": "/fake/root"})
    assert "WARN" in out and "</omx-open-backlog>" in out


def test_backlog_wrong_shape_json_emits_visible_warning(monkeypatch):
    # Valid JSON with the wrong shape ({"pages": null}) must hit the visible
    # WARN path too, not slip past json.loads into the silent outer catch.
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_resolve_backlog_root", lambda p: "/fake/root")
    monkeypatch.setattr(subprocess, "run", _fake_run([], stdout='{"pages": null}'))
    out = mod._fetch_open_backlog({"cwd": "/fake/root"})
    assert "WARN" in out and "<omx-open-backlog>" in out


def test_backlog_unparseable_stdout_emits_visible_warning(monkeypatch):
    # The 2026-07-16 audit trigger: ANY non-JSON stdout line (deprecation notice,
    # WARN, cache-vs-repo output-shape skew) previously erased the entire injected
    # backlog with zero signal. Must now degrade to the visible WARN block.
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_resolve_backlog_root", lambda p: "/fake/root")
    monkeypatch.setattr(subprocess, "run",
                        _fake_run([], stdout="DeprecationWarning: ...\n{\"pages\": []}"))
    out = mod._fetch_open_backlog({"cwd": "/fake/root"})
    assert "WARN" in out and "<omx-open-backlog>" in out


def test_backlog_no_omx_root_fail_open():
    mod = _load_handlers()
    # /  has no .omx anchor: _resolve_backlog_root raises inside, fetch degrades to ""
    assert mod._fetch_open_backlog({"cwd": "/"}) == ""


def test_backlog_unanchored_cwd_short_circuits_before_subprocess(tmp_path, monkeypatch):
    """omx-2 regression: stage == "cwd" (no anchor found by the #13 ladder) must
    short-circuit BEFORE the subprocess ever runs — not silently shell out
    `omx wiki list` against a bogus root (handlers.py:175-183 vs root.py:36,
    which never raises)."""
    mod = _load_handlers()

    def boom(cmd, **kwargs):
        raise AssertionError("subprocess.run must not be called for an unanchored cwd")
    monkeypatch.setattr(subprocess, "run", boom)
    assert mod._fetch_open_backlog({"cwd": str(tmp_path)}) == ""


def test_backlog_fetch_fits_sigalrm_budget():
    """The single unfiltered fetch must complete inside run_hook's ceiling for
    route_emit (default budget — route_emit is deliberately NOT in _BUDGETS)."""
    mod = _load_handlers()
    runner = _load(RUNNER_PATH, "omx_hook_runner_backlog")
    assert "route_emit" not in runner._BUDGETS
    assert mod._BACKLOG_FETCH_TIMEOUT_S < runner._TIMEOUT_S


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
