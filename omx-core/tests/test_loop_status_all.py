"""T10: loop-status --all (#16, spec 2.7). A pure per-run read: glob runs/*/,
report {run_id, phase, lease, marker, armed}; corrupt files degrade to phase
'unknown' + a stderr warn, never fatal."""
import json

from omx_core.lock import acquire_run_lease
from omx_core.loop import arm_loop, mark_loop_done
from omx_core.omx_paths import OmxPaths

AWARE = "2026-07-11T10:00:00+00:00"


def _p(tmp_path):
    return OmxPaths(root=str(tmp_path))


def test_all_empty_is_empty_list(tmp_path, capsys):
    from omx_core import cli
    rc = cli.main(["loop-status", "--all", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["runs"] == [] and out["armed_run"] is None


def test_all_reports_each_run_phase(tmp_path, capsys):
    from omx_core import cli
    p = _p(tmp_path)
    # run1: armed (running); run2: marker (done); run3: orphan lease (died)
    arm_loop(p, run_id="run1", now_iso=AWARE, max_runtime_s=10 ** 8, session_id="s1")
    mark_loop_done(p, "run2", reason="done", summary="x", now_iso=AWARE)
    p.run_dir("run2").mkdir(parents=True, exist_ok=True)  # marker write already made it
    acquire_run_lease(p, "run3", session_id="s3", now_iso=AWARE)
    capsys.readouterr()
    cli.main(["loop-status", "--all", "--now", AWARE, "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    by_id = {r["run_id"]: r for r in out["runs"]}
    assert by_id["run1"]["phase"] == "running" and by_id["run1"]["armed"] is True
    assert by_id["run2"]["phase"] == "done"
    assert by_id["run2"]["marker"]["reason"] == "done"
    assert by_id["run3"]["phase"] == "died"
    assert by_id["run3"]["lease"]["session_id"] == "s3"
    assert out["armed_run"] == "run1"


def test_all_corrupt_marker_degrades_to_unknown(tmp_path, capsys):
    from omx_core import cli
    p = _p(tmp_path)
    p.run_dir("run1").mkdir(parents=True)
    p.loop_marker_json("run1").write_text("{not json")
    capsys.readouterr()
    cli.main(["loop-status", "--all", "--root", str(tmp_path)])
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert out["runs"][0]["phase"] == "unknown"
    assert "run1" in cap.err  # stderr warn names the run


def test_all_mutually_exclusive_with_run_id(tmp_path, capsys):
    from omx_core import cli
    rc = cli.main(["loop-status", "--all", "--run-id", "run1", "--root", str(tmp_path)])
    assert rc == 2  # argparse mutually-exclusive group rejects both


def test_status_requires_one_of_all_or_run_id(tmp_path, capsys):
    from omx_core import cli
    rc = cli.main(["loop-status", "--root", str(tmp_path)])
    assert rc == 2  # neither given -> argparse required-group error
