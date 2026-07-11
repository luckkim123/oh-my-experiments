"""T5: loop_health circuits (#8/#9, spec 2.6). A pure function over the ledger
tail: consecutive discards (plateau) and consecutive evaluator faults (fault
streak), both reset by any keep. The verb is the AUTHORITATIVE stop path (rc 2
when tripped); the gate branch (T6) is a best-effort backstop."""
import json

import pytest

from omx_core.ledger import read_run_ledger, seed_ledger
from omx_core.loop import loop_health
from omx_core.omx_paths import OmxError, OmxPaths


def _p(tmp_path):
    return OmxPaths(root=str(tmp_path))


def _ledger(*entries):
    return {"schema_version": 1, "entries": list(entries)}


def _entry(decision, status="pass"):
    return {"decision": decision, "evaluator": {"status": status}}


# --- loop_health pure function ---

def test_health_empty_is_untripped():
    h = loop_health(_ledger())
    assert h["consecutive_discards"] == 0
    assert h["consecutive_faults"] == 0
    assert h["plateau_tripped"] is False and h["fault_tripped"] is False
    assert h["iterations"] == 0


def test_plateau_trips_on_five_discards():
    h = loop_health(_ledger(*[_entry("discard") for _ in range(5)]))
    assert h["consecutive_discards"] == 5
    assert h["plateau_tripped"] is True


def test_plateau_resets_on_keep():
    led = _ledger(_entry("discard"), _entry("discard"), _entry("keep"),
                  _entry("discard"), _entry("discard"))
    h = loop_health(led)
    assert h["consecutive_discards"] == 2  # only the tail run after the keep
    assert h["plateau_tripped"] is False
    assert h["last_kept_iteration"] == 3  # 1-based index of the keep


def test_fault_streak_trips_on_three_errors():
    led = _ledger(_entry("discard", status="error"),
                  _entry("discard", status="error"),
                  _entry("discard", status="error"))
    h = loop_health(led)
    assert h["consecutive_faults"] == 3
    assert h["fault_tripped"] is True


def test_fault_streak_resets_on_keep():
    led = _ledger(_entry("discard", status="error"),
                  _entry("keep"),
                  _entry("discard", status="error"))
    h = loop_health(led)
    assert h["consecutive_faults"] == 1
    assert h["fault_tripped"] is False


def test_thresholds_are_overridable():
    led = _ledger(_entry("discard"), _entry("discard"), _entry("discard"))
    assert loop_health(led, plateau_discards=3)["plateau_tripped"] is True
    assert loop_health(led, plateau_discards=5)["plateau_tripped"] is False


# --- read_run_ledger ---

def test_read_run_ledger_round_trip(tmp_path):
    p = _p(tmp_path)
    seed_ledger(p, "run1", baseline_commit="abc", keep_policy="pass_only")
    led = read_run_ledger(p, "run1")
    assert led["baseline_commit"] == "abc"
    assert led["entries"] == []


def test_read_run_ledger_absent_loud_fails(tmp_path):
    with pytest.raises(OmxError):
        read_run_ledger(_p(tmp_path), "nope")


def test_read_run_ledger_corrupt_loud_fails(tmp_path):
    p = _p(tmp_path)
    p.ledger_json("run1").parent.mkdir(parents=True)
    p.ledger_json("run1").write_text("{not json")
    with pytest.raises(OmxError):
        read_run_ledger(p, "run1")


# --- loop-health verb (rc 2 on trip) ---

def _seed_with_discards(p, run_id, n):
    from omx_core.ledger import append_ledger_entry, seed_ledger
    seed_ledger(p, run_id, baseline_commit="abc", keep_policy="pass_only")
    for _ in range(n):
        append_ledger_entry(p, run_id, {"decision": "discard",
                                        "evaluator": {"status": "fail"}})


def test_cli_loop_health_untripped_rc0(tmp_path, capsys):
    from omx_core import cli
    p = _p(tmp_path)
    _seed_with_discards(p, "run1", 2)
    rc = cli.main(["loop-health", "--run-id", "run1", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["plateau_tripped"] is False


def test_cli_loop_health_plateau_rc2(tmp_path, capsys):
    from omx_core import cli
    p = _p(tmp_path)
    _seed_with_discards(p, "run1", 5)
    rc = cli.main(["loop-health", "--run-id", "run1", "--root", str(tmp_path)])
    assert rc == 2
    assert "plateau" in capsys.readouterr().err


def test_cli_loop_health_absent_ledger_rc2(tmp_path, capsys):
    from omx_core import cli
    rc = cli.main(["loop-health", "--run-id", "ghost", "--root", str(tmp_path)])
    assert rc == 2  # read_run_ledger loud-fails
