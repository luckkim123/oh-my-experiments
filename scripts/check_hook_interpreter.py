#!/usr/bin/env python3
"""Verify the interpreter plugin.json's hooks will actually run under has
omx_core importable (task-13, run-completion-gate round).

Every hook in `.claude-plugin/plugin.json` is wired as a bare command name
(currently "python3"), resolved via the *caller's* PATH when Claude Code
spawns the hook subprocess -- not necessarily the interpreter `omx-core` was
`pip install -e`'d into. Every handler that imports omx_core in-process
wraps it in a blanket `except Exception: return None` (fail-open, D9) -- so
if the resolved interpreter lacks omx_core, the hook silently no-ops. No
error, no log line, no deny. Ever.

This was measured live on this machine (task-13-report.md): PATH resolves
"python3" to Homebrew's Python 3.14 (`/opt/homebrew/bin/python3`), which
does NOT have omx_core -- only python3.12 does (the interpreter `omx-core`
was pip-installed into, editable, pointing at this repo). A real headless
`claude -p --plugin-dir <repo>` session against a fixture with an
`incomplete` run confirmed the closure command was never denied; pinning
the SAME plugin.json's hook `command` to "python3.12" in a scratch copy
made the identical command deny correctly, with the identical reason text.

Ruling 39 (task 14) closed this gap for `closure_guard` and
`completion_notice` specifically -- the two handlers this round's gate
actually depends on -- by having them shell out to the `omx` CONSOLE SCRIPT
(shebang-pinned to whatever interpreter it was actually `pip install`ed
into, unaffected by what "python3" resolves to for the caller) instead of
importing omx_core in-process. Neither one needs THIS script's property
(bare "python3" importing omx_core) anymore; the permanent, automated proof
that they still fire under a broken interpreter is now
`test_end_to_end_denies_under_the_plugin_json_wired_interpreter` in
test_closure_guard.py, which actually runs bare "python3" against a real
fixture rather than only checking `import omx_core` succeeds.

`report_guard`'s ANALYSIS_ID mirror, `route_emit`, and `capture_flush`
already degrade gracefully without omx_core (their own in-code comments say
so); `loop_gate` still genuinely needs it and does NOT degrade -- an
exp-loop Stop-gate continuation silently never fires under a bare-python3
interpreter, same failure class as before this round, just unaddressed by
it. That is why this script is still worth running (it still finds a REAL,
unfixed gap) but still NOT wired into pytest as a blocking gate: on THIS
machine it will keep failing (bare "python3" still lacks omx_core, and
loop_gate still needs it), and a blanket "every hook command needs omx_core"
assertion is no longer the right binary signal now that some handlers
genuinely don't. It resolves each hook command exactly as the OS would
(`shutil.which`), then runs `<resolved> -c "import omx_core"` and reports
pass/fail per command. It does not fix anything, and the interpreter choice
(or fixing loop_gate the same way closure_guard/completion_notice were
fixed) is a decision for a human, not something this script should silently
paper over.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def hook_commands(plugin_json: Path) -> set:
    """Every distinct `command` string across all registered hooks."""
    d = json.loads(plugin_json.read_text(encoding="utf-8"))
    commands = set()
    for entries in d.get("hooks", {}).values():
        for entry in entries:
            for h in entry.get("hooks", []):
                cmd = h.get("command")
                if cmd:
                    commands.add(cmd)
    return commands


def check_command(command: str) -> dict:
    """Resolve `command` via PATH and check omx_core importability there."""
    resolved = shutil.which(command)
    if resolved is None:
        return {"command": command, "resolved": None, "omx_core_ok": False,
                 "detail": "not found on PATH"}
    try:
        out = subprocess.run(
            [resolved, "-c", "import omx_core; print(omx_core.__file__)"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"command": command, "resolved": resolved, "omx_core_ok": False,
                 "detail": f"could not run: {e!r}"}
    if out.returncode == 0:
        return {"command": command, "resolved": resolved, "omx_core_ok": True,
                 "detail": out.stdout.strip()}
    stderr = out.stderr.strip() if out.stderr else ""
    detail = stderr.splitlines()[-1] if stderr else "import failed"
    return {"command": command, "resolved": resolved, "omx_core_ok": False, "detail": detail}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Check that each plugin.json hook command resolves to an "
                     "interpreter with omx_core importable."
    )
    ap.add_argument("--repo-root", default=str(REPO_ROOT))
    args = ap.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()

    commands = hook_commands(repo_root / ".claude-plugin" / "plugin.json")
    if not commands:
        print("no hook commands found in plugin.json")
        return 1

    ok = True
    for cmd in sorted(commands):
        r = check_command(cmd)
        status = "PASS" if r["omx_core_ok"] else "FAIL"
        ok = ok and r["omx_core_ok"]
        print(f"{status}  command={r['command']!r}  resolved={r['resolved']!r}")
        print(f"      {r['detail']}")

    if not ok:
        print(
            "\nAt least one hook command resolves to an interpreter without omx_core.\n"
            "Every handler that imports omx_core fails open on ImportError (D9) --\n"
            "the corresponding hooks (report_guard/closure_guard/route_emit/loop_gate/\n"
            "capture_flush/compact_breadcrumb) silently no-op instead of doing anything,\n"
            "with no error visible anywhere. See task-13-report.md."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
