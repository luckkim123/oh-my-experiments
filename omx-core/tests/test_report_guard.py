import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "hooks" / "run_hook.py"

spec = importlib.util.spec_from_file_location("omx_hook_handlers", REPO / "hooks" / "handlers.py")
handlers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handlers)

GATED = "/tmp/x/run1/analysis/diagnose-20260705-120000/report.md"


def _payload(tool, path):
    return {"tool_name": tool, "tool_input": {"file_path": path}}


def test_denies_edit_on_gated_report():
    d = handlers.report_guard(_payload("Edit", GATED))
    assert d["hookSpecificOutput"]["permissionDecision"] == "deny"
    reason = d["hookSpecificOutput"]["permissionDecisionReason"]
    assert "RE-analysis" in reason and "OMX_SKIP_HOOKS=report_guard" in reason


def test_denies_write_on_ko_and_manifest():
    for name in ("report.ko.md", "manifest.json"):
        p = GATED.replace("report.md", name)
        assert handlers.report_guard(_payload("Write", p)) is not None


def test_allows_other_tools_and_paths():
    assert handlers.report_guard(_payload("Read", GATED)) is None
    assert handlers.report_guard(_payload("Edit", "/tmp/x/notes/report.md")) is None
    assert handlers.report_guard(
        _payload("Edit", "/tmp/x/run1/analysis/diagnose-20260705-120000/plots/a.png")) is None
    assert handlers.report_guard({"tool_name": "Edit", "tool_input": {}}) is None


def test_end_to_end_through_runner():
    r = subprocess.run([sys.executable, str(RUNNER), "report_guard"],
                       input=json.dumps(_payload("Edit", GATED)),
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 0
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_plugin_json_registers_the_hook():
    manifest = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())
    pre = manifest["hooks"]["PreToolUse"]
    assert pre[0]["matcher"] == "Edit|Write"
    cmdspec = pre[0]["hooks"][0]
    assert cmdspec["type"] == "command"
    assert "run_hook.py" in " ".join(cmdspec.get("args", [])) or "run_hook.py" in cmdspec["command"]


def test_broken_handlers_file_fails_open(tmp_path):
    tmp_hooks = tmp_path / "hooks"
    tmp_hooks.mkdir()
    shutil.copy(RUNNER, tmp_hooks / "run_hook.py")
    (tmp_hooks / "handlers.py").write_text("def broken(:\n    pass\n")

    r = subprocess.run([sys.executable, str(tmp_hooks / "run_hook.py"), "ping"],
                       input=json.dumps({}),
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 0
    assert json.loads(r.stdout) == {"pong": True}
