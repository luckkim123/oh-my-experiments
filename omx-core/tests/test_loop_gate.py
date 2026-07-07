"""T7+T8: thin Stop-hook loop gate (spec 2.4) — arm/disarm verbs (the D9
guarantee layer) and the loop_gate handler cascade."""
import importlib.util
import json
from pathlib import Path

import pytest

from omx_core.loop import LOOP_HARD_CAP_DEFAULT, arm_loop, disarm_loop
from omx_core.omx_paths import OmxError, OmxPaths
from omx_core.state import load_state

REPO = Path(__file__).resolve().parents[2]
HANDLERS_PATH = REPO / "hooks" / "handlers.py"

NOW = "2026-07-07T10:00:00+00:00"          # aware UTC — the loop clock contract
LATER = "2026-07-07T13:00:00+00:00"


def _paths(tmp_path):
    return OmxPaths(root=str(tmp_path))


def test_arm_writes_envelope(tmp_path):
    p = _paths(tmp_path)
    env = arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=7200)
    assert env["run_id"] == "run1"
    assert env["iteration"] == 0
    assert env["hard_cap"] == LOOP_HARD_CAP_DEFAULT == 50
    assert env["adopted_session"] is None
    assert env["deadline"] == "2026-07-07T12:00:00+00:00"
    assert load_state(p)["active_loop"] == env


def test_arm_twice_loud_fails(tmp_path):
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=60)
    with pytest.raises(OmxError):
        arm_loop(p, run_id="run2", now_iso=NOW, max_runtime_s=60)


def test_arm_requires_positive_runtime_and_cap(tmp_path):
    p = _paths(tmp_path)
    with pytest.raises(OmxError):
        arm_loop(p, run_id="r", now_iso=NOW, max_runtime_s=0)
    with pytest.raises(OmxError):
        arm_loop(p, run_id="r", now_iso=NOW, max_runtime_s=60, hard_cap=0)


def test_disarm_reports_and_is_idempotent(tmp_path):
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=60)
    out = disarm_loop(p, reason="done")
    assert out == {"was_armed": True, "iteration": 0, "reason": "done"}
    assert load_state(p)["active_loop"] is None
    assert disarm_loop(p)["was_armed"] is False


def test_cli_loop_arm_disarm_roundtrip(tmp_path, capsys):
    from omx_core import cli
    rc = cli.main(["loop-arm", "--run-id", "run1", "--max-runtime", "3600",
                   "--now", NOW, "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["deadline"] == "2026-07-07T11:00:00+00:00"
    rc = cli.main(["loop-disarm", "--reason", "done", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["was_armed"] is True


def test_cli_loop_arm_twice_rc2(tmp_path, capsys):
    # cli.main() swallows SystemExit(str) and returns rc 2 (cli.py:1499).
    from omx_core import cli
    cli.main(["loop-arm", "--run-id", "run1", "--max-runtime", "60",
              "--now", NOW, "--root", str(tmp_path)])
    capsys.readouterr()
    rc = cli.main(["loop-arm", "--run-id", "run2", "--max-runtime", "60",
                   "--now", NOW, "--root", str(tmp_path)])
    assert rc == 2


def test_cli_loop_status_reports_armed(tmp_path, capsys):
    from omx_core import cli
    cli.main(["loop-arm", "--run-id", "run1", "--max-runtime", "60",
              "--now", NOW, "--root", str(tmp_path)])
    capsys.readouterr()
    rc = cli.main(["loop-status", "--run-id", "run1", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["armed"]["run_id"] == "run1"
