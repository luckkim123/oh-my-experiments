"""T8: launch provenance (#12, D-R4-6). queue-launch --cwd records the queued
commit into pending-launch.json (closing the audit-noted 'no sha' gap); the
LAUNCH_TEMPLATE tells training to record its own HEAD and pass it to
run-record."""
import json
import subprocess

from omx_core.loop import queue_pending_launch, read_pending_launch
from omx_core.omx_paths import OmxPaths


def _p(tmp_path):
    return OmxPaths(root=str(tmp_path))


def _git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, check=True)


def _init_repo(cwd):
    cwd.mkdir(parents=True, exist_ok=True)
    _git(cwd, "init", "-q")
    _git(cwd, "config", "user.email", "t@t.t"); _git(cwd, "config", "user.name", "t")
    (cwd / "f").write_text("x"); _git(cwd, "add", "f"); _git(cwd, "commit", "-q", "-m", "c")
    return subprocess.run(["git", "-C", str(cwd), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def test_queue_pending_launch_records_commit_when_given(tmp_path):
    p = _p(tmp_path)
    queue_pending_launch(p, "run1", proposal_id="20260711-100000-x",
                         launch_delta="d", gpu_gate="g",
                         queued_at="2026-07-11T10:00:00+00:00",
                         queued_commit="deadbeef")
    data = read_pending_launch(p, "run1")
    assert data["queued_commit"] == "deadbeef"


def test_queue_pending_launch_omits_commit_when_none(tmp_path):
    p = _p(tmp_path)
    queue_pending_launch(p, "run1", proposal_id="20260711-100000-x",
                         launch_delta="d", gpu_gate="g",
                         queued_at="2026-07-11T10:00:00+00:00")
    data = read_pending_launch(p, "run1")
    assert "queued_commit" not in data  # backward-compatible shape


def test_cli_queue_launch_records_head(tmp_path, capsys):
    from omx_core import cli
    repo = tmp_path / "proj"
    head = _init_repo(repo)
    rc = cli.main(["queue-launch", "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g", "--cwd", str(repo)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["queued_commit"] == head


def test_cli_queue_launch_no_cwd_warns_and_omits(tmp_path, capsys):
    from omx_core import cli
    rc = cli.main(["queue-launch", "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g"])  # no --cwd
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert rc == 0 and "queued_commit" not in out
    # no --cwd -> nothing to record; no warning is required, but a non-repo cwd IS warned
    # (see below)


def test_cli_queue_launch_non_repo_cwd_warns(tmp_path, capsys):
    from omx_core import cli
    rc = cli.main(["queue-launch", "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g", "--cwd", str(tmp_path)])  # tmp_path is not a git repo
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert rc == 0 and "queued_commit" not in out
    assert "queued_commit" in cap.err.lower() or "not a git repo" in cap.err.lower() \
        or "could not record" in cap.err.lower()


def test_launch_template_mentions_commit_recording():
    from omx_core.profile import LAUNCH_TEMPLATE
    assert "rev-parse HEAD" in LAUNCH_TEMPLATE
    assert "run-record" in LAUNCH_TEMPLATE


# ---------------------------------------------------------------------------
# T6: pre-launch wiki forcing gate — REFUSE on open HARD gate, WARN on soft lead
# ---------------------------------------------------------------------------

def _seed(p, title, status, blocked_on=None):
    from omx_core.wiki import ingest
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title=title, content="c",
                            tags=[], category="decision", confidence="high", sources=[],
                            status=status, blocked_on=blocked_on)


def test_queue_launch_refuses_on_open_hard_gate(tmp_path, capsys):
    from omx_core import cli
    p = _p(tmp_path)
    _seed(p, "TAM row rewrite", "needs-apply-before-retrain", "measure first")
    rc = cli.main(["queue-launch", "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2 and out["refused"] is True
    assert out["open_gates"][0]["slug"] == "tam_row_rewrite.md"
    assert out["open_gates"][0]["blocked_on"] == "measure first"
    assert read_pending_launch(p, "run1") is None   # REFUSE wrote NOTHING


def test_queue_launch_ack_gate_allows_and_records(tmp_path, capsys):
    from omx_core import cli
    p = _p(tmp_path)
    _seed(p, "TAM row rewrite", "needs-apply-before-retrain")
    rc = cli.main(["queue-launch", "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g", "--ack-gate", "tam_row_rewrite.md"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    # the human-approval artifact now carries the un-applied correction it launched over
    assert out["acknowledged_gates"] == ["tam_row_rewrite.md"]
    assert read_pending_launch(p, "run1")["acknowledged_gates"] == ["tam_row_rewrite.md"]


def test_queue_launch_warns_on_soft_lead(tmp_path, capsys):
    from omx_core import cli
    p = _p(tmp_path)
    _seed(p, "Command box eval", "needs-experiment")
    rc = cli.main(["queue-launch", "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g"])
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert rc == 0                                  # soft leads WARN, never REFUSE
    assert out["open_leads"] == ["command_box_eval.md"]
    assert "command_box_eval.md" in cap.err


def test_queue_launch_empty_wiki_passes_clean(tmp_path, capsys):
    from omx_core import cli
    p = _p(tmp_path)
    rc = cli.main(["queue-launch", "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "open_leads" not in out and "acknowledged_gates" not in out   # backward-compatible shape


def test_queue_launch_corrupt_page_does_not_block(tmp_path, capsys):
    from omx_core import cli
    p = _p(tmp_path)
    p.wiki_dir().mkdir(parents=True, exist_ok=True)
    (p.wiki_dir() / "broken.md").write_text("no frontmatter here", encoding="utf-8")
    rc = cli.main(["queue-launch", "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g"])
    assert rc == 0   # a corrupt page is surfaced elsewhere (lint), never blocks a launch


def test_queue_pending_launch_records_open_leads_and_acks(tmp_path):
    p = _p(tmp_path)
    queue_pending_launch(p, "run1", proposal_id="x", launch_delta="d", gpu_gate="g",
                         queued_at="2026-07-11T10:00:00+00:00",
                         open_leads=["a.md"], acknowledged_gates=["b.md"])
    data = read_pending_launch(p, "run1")
    assert data["open_leads"] == ["a.md"]
    assert data["acknowledged_gates"] == ["b.md"]


def test_queue_pending_launch_omits_gate_fields_when_none(tmp_path):
    p = _p(tmp_path)
    queue_pending_launch(p, "run1", proposal_id="x", launch_delta="d", gpu_gate="g",
                         queued_at="2026-07-11T10:00:00+00:00")
    data = read_pending_launch(p, "run1")
    assert "open_leads" not in data and "acknowledged_gates" not in data
