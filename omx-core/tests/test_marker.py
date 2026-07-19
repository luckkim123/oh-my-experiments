"""T3/T4: loop-completion marker (spec 2.5, D-R4-8). mark_loop_done writes
runs/<run_id>/loop-status.json; loop-status folds it into a phase field:
  done   -> marker present
  running-> armed for this run, deadline live
  died   -> armed + deadline passed + no marker, OR an orphan lease
  idle   -> none of the above."""
import json

from omx_core.lock import acquire_run_lease
from omx_core.loop import arm_loop, mark_loop_done
from omx_core.omx_paths import OmxPaths

AWARE = "2026-07-11T10:00:00+00:00"
PAST = "2020-01-01T00:00:00+00:00"


def _p(tmp_path):
    return OmxPaths(root=str(tmp_path))


def test_mark_loop_done_writes_marker(tmp_path):
    p = _p(tmp_path)
    out = mark_loop_done(p, "run1", reason="done", summary="iteration 3", now_iso=AWARE)
    assert out["phase"] == "done" and out["reason"] == "done"
    on_disk = json.loads(p.loop_marker_json("run1").read_text())
    assert on_disk["schema_version"] == 1
    assert on_disk["reason"] == "done"
    assert on_disk["summary"] == "iteration 3"
    assert on_disk["ended_at"] == AWARE


def test_mark_loop_done_overwrites(tmp_path):
    p = _p(tmp_path)
    mark_loop_done(p, "run1", reason="deadline", summary="a", now_iso=AWARE)
    mark_loop_done(p, "run1", reason="done", summary="b", now_iso=AWARE)
    on_disk = json.loads(p.loop_marker_json("run1").read_text())
    assert on_disk["reason"] == "done" and on_disk["summary"] == "b"


def test_cli_loop_mark_done(tmp_path, capsys):
    from omx_core import cli
    rc = cli.main(["loop-mark-done", "--run-id", "run1", "--reason", "done",
                   "--summary", "single pass", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["phase"] == "done"
    assert _p(tmp_path).loop_marker_json("run1").is_file()


def test_cli_loop_mark_done_bad_reason_rc2(tmp_path, capsys):
    from omx_core import cli
    rc = cli.main(["loop-mark-done", "--run-id", "run1", "--reason", "nope",
                   "--root", str(tmp_path)])
    assert rc == 2  # argparse choices reject it


# --- phase derivation (loop-status --run-id) ---

def _status_phase(tmp_path, run_id, capsys, now=AWARE):
    from omx_core import cli
    capsys.readouterr()
    cli.main(["loop-status", "--run-id", run_id, "--now", now, "--root", str(tmp_path)])
    return json.loads(capsys.readouterr().out)["phase"]


def test_phase_idle_when_nothing(tmp_path, capsys):
    assert _status_phase(tmp_path, "run1", capsys) == "idle"


def test_phase_running_when_armed_live(tmp_path, capsys):
    p = _p(tmp_path)
    arm_loop(p, run_id="run1", now_iso=AWARE, max_runtime_s=10 ** 8, session_id="s")
    assert _status_phase(tmp_path, "run1", capsys) == "running"


def test_phase_done_when_marker(tmp_path, capsys):
    p = _p(tmp_path)
    mark_loop_done(p, "run1", reason="done", summary="x", now_iso=AWARE)
    assert _status_phase(tmp_path, "run1", capsys) == "done"


def test_phase_done_wins_over_armed(tmp_path, capsys):
    # marker present takes precedence even if an envelope still names the run
    p = _p(tmp_path)
    arm_loop(p, run_id="run1", now_iso=AWARE, max_runtime_s=10 ** 8, session_id="s")
    mark_loop_done(p, "run1", reason="done", summary="x", now_iso=AWARE)
    assert _status_phase(tmp_path, "run1", capsys) == "done"


def test_phase_died_when_armed_expired_no_marker(tmp_path, capsys):
    p = _p(tmp_path)
    arm_loop(p, run_id="run1", now_iso=PAST, max_runtime_s=1, session_id="s")
    # now is far past the deadline, no marker -> died
    assert _status_phase(tmp_path, "run1", capsys, now=AWARE) == "died"


def test_phase_died_on_orphan_lease(tmp_path, capsys):
    # a lease present with NO armed envelope naming the run -> orphan -> died
    p = _p(tmp_path)
    acquire_run_lease(p, "run1", session_id="s", now_iso=AWARE)
    assert _status_phase(tmp_path, "run1", capsys) == "died"
