import json
import subprocess
import sys
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[2] / "hooks" / "run_hook.py"


def _run(handler, payload, env_extra=None):
    import os
    env = dict(os.environ)
    env.pop("OMX_DISABLE", None)
    env.pop("OMX_SKIP_HOOKS", None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(RUNNER), handler],
        input=json.dumps(payload) if payload is not None else "not json{",
        capture_output=True, text=True, env=env, timeout=10)


def test_ping_handler_answers():
    r = _run("ping", {"hello": 1})
    assert r.returncode == 0
    assert json.loads(r.stdout)["pong"] is True


def test_unknown_handler_fails_open():
    r = _run("nonexistent", {"a": 1})
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_malformed_stdin_fails_open():
    r = _run("ping", None)  # sends invalid JSON
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_omx_disable_short_circuits():
    r = _run("ping", {"hello": 1}, {"OMX_DISABLE": "1"})
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_omx_skip_hooks_short_circuits_named():
    r = _run("ping", {"hello": 1}, {"OMX_SKIP_HOOKS": "other,ping"})
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_omx_skip_hooks_other_name_still_runs():
    r = _run("ping", {"hello": 1}, {"OMX_SKIP_HOOKS": "report_guard"})
    assert r.returncode == 0
    assert json.loads(r.stdout)["pong"] is True


def test_timeout_fails_open():
    r = _run("sleep", {"x": 1})
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_no_sigalrm_platform_is_fail_open(monkeypatch):
    # M-5: with SIGALRM absent (Windows shape), the runner must neither register
    # the alarm nor crash in the finally-cleanup -- rc 0, fail-open. Needs direct
    # module state control (_HAS_ALARM=False), which the subprocess-based _run()
    # helper above cannot express, so this one test imports run_hook.py directly.
    import importlib.util
    import io
    import json as _json
    import sys as _sys
    spec = importlib.util.spec_from_file_location("run_hook_m5", str(RUNNER))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_HAS_ALARM", False)
    monkeypatch.setattr(_sys, "stdin", io.StringIO(_json.dumps({"hello": 1})))
    monkeypatch.setattr(_sys, "argv", ["run_hook.py", "ping"])
    rc = mod.main()
    assert rc == 0  # fail-open; no AttributeError escaped from the guarded alarm(0)
