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


# --- R4 T4: arm/disarm lease + marker wiring (spec 2.2) ---

def test_arm_acquires_lease_keyed_by_session(tmp_path):
    from omx_core.lock import read_run_lease
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=60, session_id="sess-A")
    lease = read_run_lease(p, "run1")
    assert lease is not None and lease["session_id"] == "sess-A"


def test_arm_without_session_still_acquires_lease(tmp_path):
    from omx_core.lock import read_run_lease
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=60)
    lease = read_run_lease(p, "run1")
    assert lease is not None and lease["session_id"] is None


def test_arm_when_already_armed_loud_fails(tmp_path):
    # the state envelope already holds a loop for this root -> the already-armed
    # guard fires (this path never reaches the lease code; a DIFFERENT run_id is
    # used so the guard, not the lease, is what trips).
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=60, session_id="sess-A")
    with pytest.raises(OmxError) as ei:
        arm_loop(p, run_id="run2", now_iso=NOW, max_runtime_s=60, session_id="sess-B")
    assert "already armed" in str(ei.value)


def test_arm_loud_fails_on_contended_lease(tmp_path):
    # genuine lease contention: a young lease for run1 owned by sess-A exists with
    # NO armed envelope (so the already-armed guard passes and _crit reaches
    # acquire_run_lease), then arming run1 from sess-B must loud-fail naming the
    # owning session sess-A.
    from omx_core.lock import acquire_run_lease
    p = _paths(tmp_path)
    acquire_run_lease(p, "run1", session_id="sess-A", now_iso=NOW)  # young lease, no arm
    with pytest.raises(OmxError) as ei:
        arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=60, session_id="sess-B")
    assert "sess-A" in str(ei.value)  # names the owning session


def test_arm_clears_stale_marker(tmp_path):
    # a re-arm of a run that previously finished must not leave a 'done' marker
    from omx_core.loop import mark_loop_done
    p = _paths(tmp_path)
    mark_loop_done(p, "run1", reason="done", summary="old", now_iso=NOW)
    assert p.loop_marker_json("run1").exists()
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=60, session_id="s")
    assert not p.loop_marker_json("run1").exists()  # fresh loop => fresh marker slot


def test_disarm_writes_marker_and_releases_lease(tmp_path):
    from omx_core.lock import read_run_lease
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=60, session_id="sess-A")
    out = disarm_loop(p, reason="done", now_iso=LATER)
    assert out == {"was_armed": True, "iteration": 0, "reason": "done"}
    # lease released unconditionally
    assert read_run_lease(p, "run1") is None
    # marker written for the armed run with the disarm reason + aware ended_at
    marker = json.loads(p.loop_marker_json("run1").read_text())
    assert marker["reason"] == "done" and marker["ended_at"] == LATER


def test_disarm_computes_ended_at_when_none(tmp_path):
    # the handler path passes no now_iso: disarm computes an aware-UTC instant
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=60, session_id="s")
    disarm_loop(p, reason="cancel")  # now_iso defaults to None
    marker = json.loads(p.loop_marker_json("run1").read_text())
    assert marker["ended_at"].endswith("+00:00")  # aware UTC


def test_disarm_unarmed_is_idempotent_no_marker(tmp_path):
    p = _paths(tmp_path)
    out = disarm_loop(p, reason="cancel")
    assert out["was_armed"] is False
    # nothing armed -> no marker written (there is no run to mark)
    assert not (tmp_path / ".omx" / "runs").exists() or \
        not any((tmp_path / ".omx" / "runs").glob("*/loop-status.json"))


def test_cli_loop_arm_threads_session_id(tmp_path, capsys):
    from omx_core import cli
    from omx_core.lock import read_run_lease
    rc = cli.main(["loop-arm", "--run-id", "run1", "--max-runtime", "3600",
                   "--now", NOW, "--session-id", "sess-CLI", "--root", str(tmp_path)])
    assert rc == 0
    capsys.readouterr()
    assert read_run_lease(_paths(tmp_path), "run1")["session_id"] == "sess-CLI"


# --- T8: loop_gate handler cascade (spec 2.4) ---

def _load_handlers():
    spec = importlib.util.spec_from_file_location("omx_handlers_gate", str(HANDLERS_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _payload(tmp_path, sid="sess-A"):
    return {"cwd": str(tmp_path), "session_id": sid}


def test_gate_allows_when_not_armed(tmp_path):
    (tmp_path / ".omx").mkdir()
    assert _load_handlers().loop_gate(_payload(tmp_path)) is None


def test_gate_blocks_adopts_and_increments(tmp_path):
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=10 ** 8)
    out = _load_handlers().loop_gate(_payload(tmp_path, "sess-A"))
    assert out["decision"] == "block"
    assert "run1" in out["reason"] and "iteration 1" in out["reason"]
    assert "NEVER execute a training launch" in out["reason"]  # D4, frozen
    env = load_state(p)["active_loop"]
    assert env["adopted_session"] == "sess-A" and env["iteration"] == 1


def test_gate_ignores_other_sessions_after_adoption(tmp_path):
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=10 ** 8)
    mod = _load_handlers()
    mod.loop_gate(_payload(tmp_path, "sess-A"))
    assert mod.loop_gate(_payload(tmp_path, "sess-B")) is None
    assert load_state(p)["active_loop"]["iteration"] == 1  # untouched by sess-B


def test_gate_expired_deadline_self_disarms(tmp_path):
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso="2020-01-01T00:00:00+00:00", max_runtime_s=1)
    assert _load_handlers().loop_gate(_payload(tmp_path)) is None
    assert load_state(p)["active_loop"] is None  # disarmed(reason=deadline)


def test_gate_hard_cap_self_disarms(tmp_path):
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=10 ** 8, hard_cap=2)
    mod = _load_handlers()
    assert mod.loop_gate(_payload(tmp_path))["decision"] == "block"
    assert mod.loop_gate(_payload(tmp_path))["decision"] == "block"
    assert mod.loop_gate(_payload(tmp_path)) is None  # 3rd stop: cap reached
    assert load_state(p)["active_loop"] is None


def test_gate_mixed_clock_fails_open(tmp_path):
    # A NAIVE deadline in the envelope (should be impossible via loop-arm) makes
    # deadline_passed raise; the handler must fail-open (allow), never crash.
    from omx_core.state import load_state as ls, save_state as ss
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=60)
    state = ls(p)
    state["active_loop"]["deadline"] = "2026-07-07T12:00:00"  # naive
    ss(p, state)
    assert _load_handlers().loop_gate(_payload(tmp_path)) is None


def test_gate_fails_open_on_garbage_payload():
    assert _load_handlers().loop_gate({"cwd": None}) is None


# --- R4 T6: loop_gate state-lock + circuit backstop (spec 2.6) ---

def test_gate_self_disarm_releases_lease_and_marks(tmp_path):
    # hard_cap self-disarm must clean up the lease AND write the marker (the
    # disarm path is now authoritative — critic C2).
    from omx_core.lock import read_run_lease
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=10 ** 8, hard_cap=1,
             session_id="sess-A")
    mod = _load_handlers()
    assert mod.loop_gate(_payload(tmp_path))["decision"] == "block"  # iter -> 1
    assert mod.loop_gate(_payload(tmp_path)) is None                 # cap reached -> disarm
    assert load_state(p)["active_loop"] is None
    assert read_run_lease(p, "run1") is None                         # lease released
    marker = json.loads(p.loop_marker_json("run1").read_text())
    assert marker["reason"] == "hard_cap"


def test_gate_deadline_self_disarm_releases_lease_and_marks(tmp_path):
    from omx_core.lock import read_run_lease
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso="2020-01-01T00:00:00+00:00", max_runtime_s=1,
             session_id="s")
    assert _load_handlers().loop_gate(_payload(tmp_path)) is None
    assert read_run_lease(p, "run1") is None
    assert json.loads(p.loop_marker_json("run1").read_text())["reason"] == "deadline"


def test_gate_circuit_backstop_disarms_on_plateau(tmp_path):
    # 5 consecutive discards in the ledger -> the gate's best-effort backstop
    # self-disarms with reason 'plateau' and allows the stop.
    from omx_core.ledger import append_ledger_entry, seed_ledger
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=10 ** 8, session_id="s")
    seed_ledger(p, "run1", baseline_commit="abc", keep_policy="pass_only")
    for _ in range(5):
        append_ledger_entry(p, "run1", {"decision": "discard",
                                        "evaluator": {"status": "fail"}})
    assert _load_handlers().loop_gate(_payload(tmp_path)) is None
    assert load_state(p)["active_loop"] is None
    marker = json.loads(p.loop_marker_json("run1").read_text())
    assert marker["reason"] == "plateau"


def test_gate_circuit_backstop_disarms_on_fault_streak(tmp_path):
    from omx_core.ledger import append_ledger_entry, seed_ledger
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=10 ** 8, session_id="s")
    seed_ledger(p, "run1", baseline_commit="abc", keep_policy="pass_only")
    for _ in range(3):
        append_ledger_entry(p, "run1", {"decision": "discard",
                                        "evaluator": {"status": "error"}})
    assert _load_handlers().loop_gate(_payload(tmp_path)) is None
    marker = json.loads(p.loop_marker_json("run1").read_text())
    assert marker["reason"] == "fault_circuit"


def test_gate_circuit_backstop_honors_profile_override(tmp_path):
    # metrics.yaml sets plateau_discards=2 -> the backstop must trip on 2
    # discards, not the hardcoded default of 5 (review finding: handlers.py
    # must read profile overrides the same way _cmd_loop_health does).
    from omx_core.ledger import append_ledger_entry, seed_ledger
    p = _paths(tmp_path)
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "metrics.yaml").write_text("plateau_discards: 2\n", encoding="utf-8")
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=10 ** 8, session_id="s")
    seed_ledger(p, "run1", baseline_commit="abc", keep_policy="pass_only")
    for _ in range(2):
        append_ledger_entry(p, "run1", {"decision": "discard",
                                        "evaluator": {"status": "fail"}})
    assert _load_handlers().loop_gate(_payload(tmp_path)) is None
    assert load_state(p)["active_loop"] is None
    marker = json.loads(p.loop_marker_json("run1").read_text())
    assert marker["reason"] == "plateau"


def test_gate_backstop_fail_opens_on_missing_ledger(tmp_path):
    # a loop that never recorded -> read_run_ledger loud-fails INSIDE the branch
    # -> the branch is skipped (fail-open), the gate blocks normally.
    p = _paths(tmp_path)
    arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=10 ** 8, session_id="s")
    out = _load_handlers().loop_gate(_payload(tmp_path))
    assert out["decision"] == "block"  # no ledger -> backstop skipped, normal block


def test_cli_loop_disarm_accepts_circuit_reasons(tmp_path, capsys):
    from omx_core import cli
    p = _paths(tmp_path)
    for reason in ("plateau", "fault_circuit"):
        arm_loop(p, run_id="run1", now_iso=NOW, max_runtime_s=60, session_id="s")
        capsys.readouterr()
        rc = cli.main(["loop-disarm", "--reason", reason, "--root", str(tmp_path)])
        capsys.readouterr()
        assert rc == 0  # the new reasons are valid argparse choices
