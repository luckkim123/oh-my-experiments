"""v0.8.0 campaign liveness: CLI wiring (campaign-drift verb, --label/
--predecessor, byproduct events in report-coverage/queue-launch)."""
import json
import subprocess

from omx_core.cli import main

NOW_TREE_YAML = """\
version: 1
trees:
  index:
    root: experiments
    levels: [group]
run_id:
  grammar: "<label>[_<tag>]_<ts>"
  ts_format: "%y%m%d_%H%M%S"
  tag: optional
run_dir:
  eval_pattern: "eval/<mode>_<ts>"
  eval_modes: [static]
walk:
  ignore: ["legacy", "_*"]
"""


def _make_tree_project(tmp_path, groups):
    """Mirrors test_campaign_drift.py's _make_project — a tree.yaml + runs
    on disk so campaign_drift can walk them."""
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "tree.yaml").write_text(NOW_TREE_YAML, encoding="utf-8")
    for group, runs in groups.items():
        for run_id in runs:
            (tmp_path / "experiments" / group / run_id).mkdir(parents=True)


# --- 1+2: campaign-drift verb ---------------------------------------------

def test_campaign_drift_reports_unregistered_group(tmp_path, capsys):
    _make_tree_project(tmp_path, {"groupa": ["runa_tag_260722_120000"]})
    rc = main(["campaign-drift", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["unregistered"] == [{"group": "groupa", "runs": 1}]


def test_campaign_drift_adopt_then_clean(tmp_path, capsys):
    _make_tree_project(tmp_path, {"groupa": ["runa_tag_260722_120000"]})
    rc = main(["campaign-drift", "--root", str(tmp_path), "--adopt"])
    assert rc == 0
    adopted = json.loads(capsys.readouterr().out)
    assert adopted["adopted"] == ["groupa"]
    rc2 = main(["campaign-drift", "--root", str(tmp_path)])
    assert rc2 == 0
    out2 = json.loads(capsys.readouterr().out)
    assert out2["ok"] is True


# --- 3: campaign-plan-add --label ------------------------------------------

def test_campaign_plan_add_label_surfaced_in_status(tmp_path, capsys):
    main(["campaign-init", "--root", str(tmp_path), "--id", "camp1"])
    capsys.readouterr()
    rc = main(["campaign-plan-add", "--root", str(tmp_path), "--id", "camp1",
               "--proposal-id", "p1", "--label", "C2"])
    assert rc == 0
    capsys.readouterr()
    main(["campaign-status", "--root", str(tmp_path), "--id", "camp1"])
    out = json.loads(capsys.readouterr().out)
    assert out["plan"][0]["label"] == "C2"


# --- 4: campaign-init --predecessor ----------------------------------------

def test_campaign_init_predecessor_surfaced_in_list(tmp_path, capsys):
    main(["campaign-init", "--root", str(tmp_path), "--id", "old"])
    capsys.readouterr()
    rc = main(["campaign-init", "--root", str(tmp_path), "--id", "new",
               "--predecessor", "old"])
    assert rc == 0
    capsys.readouterr()
    main(["campaign-list", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    listed = {c["campaign_id"]: c for c in out["campaigns"]}
    assert listed["new"]["predecessor"] == "old"
    assert "predecessor" not in listed["old"]


# --- 5: report-coverage byproduct ------------------------------------------

def _mk_analysis_report(tmp_path, group="groupa", run="run1",
                        analysis="diagnose-20260722-120000"):
    # mirrors test_integrity.py's _mk_analysis, nested under experiments/<group>/
    # (D-R2-5) so record_analyzed can derive group = run_dir.parent.name.
    d = tmp_path / "experiments" / group / run / "analysis" / analysis
    d.mkdir(parents=True)
    rp = d / "report.md"
    rp.write_text("# r\n")
    return rp


def _write_vacuous_coverage_profile(tmp_path):
    # reuses test_integrity.py::test_coverage_cli_stamps_on_ok's smallest
    # passing setup: no groups/markers declared -> coverage gate passes vacuously.
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True, exist_ok=True)
    (prof / "metrics.yaml").write_text("output_root: experiments\n")


def test_report_coverage_records_analyzed_event_and_dedups(tmp_path, capsys):
    _write_vacuous_coverage_profile(tmp_path)
    rp = _mk_analysis_report(tmp_path)
    rc = main(["report-coverage", "--path", str(rp), "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["stamped"] is True
    assert out["campaign_event"] == "logged"
    ledger = tmp_path / ".omx" / "campaigns" / "groupa" / "ledger.jsonl"
    events = [json.loads(ln) for ln in ledger.read_text().splitlines() if ln.strip()]
    assert len(events) == 1 and events[0]["event"] == "analyzed"

    # running the exact same gate again must dedup (same report path)
    rc2 = main(["report-coverage", "--path", str(rp), "--root", str(tmp_path)])
    assert rc2 == 0
    out2 = json.loads(capsys.readouterr().out)
    assert out2["campaign_event"] == "duplicate"
    events2 = [json.loads(ln) for ln in ledger.read_text().splitlines() if ln.strip()]
    assert len(events2) == 1


# --- 6: queue-launch byproduct ---------------------------------------------

def _git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], capture_output=True,
                          text=True, check=True)


def _init_repo(cwd):
    # mirrors test_queue_launch.py's _init_repo (queue-launch requires --cwd
    # to be a git repo to record queued_commit; irrelevant here but keeps the
    # existing invocation shape intact).
    cwd.mkdir(parents=True, exist_ok=True)
    _git(cwd, "init", "-q")
    _git(cwd, "config", "user.email", "t@t.t")
    _git(cwd, "config", "user.name", "t")
    (cwd / "f").write_text("x")
    _git(cwd, "add", "f")
    _git(cwd, "commit", "-q", "-m", "c")


def _queue_launch(tmp_path, repo, run_id, proposal_id):
    return main(["queue-launch", "--root", str(tmp_path), "--run-id", run_id,
                 "--proposal-id", proposal_id, "--launch-delta", "d",
                 "--gpu-gate", "g", "--cwd", str(repo)])


def test_queue_launch_records_launched_event(tmp_path, capsys):
    repo = tmp_path / "proj"
    _init_repo(repo)
    main(["campaign-init", "--root", str(tmp_path), "--id", "camp1"])
    capsys.readouterr()
    main(["campaign-plan-add", "--root", str(tmp_path), "--id", "camp1",
          "--proposal-id", "p1"])
    capsys.readouterr()

    rc = _queue_launch(tmp_path, repo, "run1", "p1")
    assert rc == 0
    capsys.readouterr()
    ledger = tmp_path / ".omx" / "campaigns" / "camp1" / "ledger.jsonl"
    events = [json.loads(ln) for ln in ledger.read_text().splitlines() if ln.strip()]
    assert len(events) == 1
    assert events[0]["event"] == "launched"
    assert events[0]["run_id"] == "run1"
    assert events[0]["data"]["proposal_id"] == "p1"

    # a second launch with a fresh run_id -> a second event
    rc2 = _queue_launch(tmp_path, repo, "run2", "p1")
    assert rc2 == 0
    events2 = [json.loads(ln) for ln in ledger.read_text().splitlines() if ln.strip()]
    assert len(events2) == 2


def test_queue_launch_unplanned_proposal_no_event_rc_still_0(tmp_path, capsys):
    repo = tmp_path / "proj"
    _init_repo(repo)
    rc = _queue_launch(tmp_path, repo, "run1", "never-planned")
    assert rc == 0
    campaigns_dir = tmp_path / ".omx" / "campaigns"
    assert not campaigns_dir.exists() or not any(campaigns_dir.iterdir())
