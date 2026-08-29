"""T8: launch provenance (#12, D-R4-6). queue-launch --cwd records the queued
commit into pending-launch.json (closing the audit-noted 'no sha' gap); the
LAUNCH_TEMPLATE tells training to record its own HEAD and pass it to
run-record."""
import json
import pathlib
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
    _git(cwd, "config", "user.email", "t@t.t")
    _git(cwd, "config", "user.name", "t")
    (cwd / "f").write_text("x")
    _git(cwd, "add", "f")
    _git(cwd, "commit", "-q", "-m", "c")
    return subprocess.run(["git", "-C", str(cwd), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def test_queue_pending_launch_records_commit_when_given(tmp_path):
    p = _p(tmp_path)
    queue_pending_launch(p, "run1", proposal_id="20260711-100000-x",
                         launch_delta="d", gpu_gate="g",
                         queued_at="2026-07-11T10:00:00+00:00",
                         queued_commit="deadbeef", predicted_outcome="test prediction")
    data = read_pending_launch(p, "run1")
    assert data["queued_commit"] == "deadbeef"


def test_queue_pending_launch_omits_commit_when_none(tmp_path):
    p = _p(tmp_path)
    queue_pending_launch(p, "run1", proposal_id="20260711-100000-x",
                         launch_delta="d", gpu_gate="g",
                         queued_at="2026-07-11T10:00:00+00:00", predicted_outcome="test prediction")
    data = read_pending_launch(p, "run1")
    assert "queued_commit" not in data  # backward-compatible shape


def test_cli_queue_launch_records_head(tmp_path, capsys):
    from omx_core import cli
    repo = tmp_path / "proj"
    head = _init_repo(repo)
    rc = cli.main(["queue-launch", "--predicted-outcome", "test prediction", "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g", "--cwd", str(repo)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["queued_commit"] == head


def test_cli_queue_launch_no_cwd_warns_and_omits(tmp_path, capsys):
    from omx_core import cli
    rc = cli.main(["queue-launch", "--predicted-outcome", "test prediction", "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g"])  # no --cwd
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert rc == 0 and "queued_commit" not in out
    # no --cwd -> nothing to record; no warning is required, but a non-repo cwd IS warned
    # (see below)


def test_cli_queue_launch_non_repo_cwd_warns(tmp_path, capsys):
    from omx_core import cli
    rc = cli.main(["queue-launch", "--predicted-outcome", "test prediction", "--root", str(tmp_path), "--run-id", "run1",
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

def _anchor(root):
    """A git anchor, so `write_knowledge` takes the edit path rather than
    supersede (store-spec section 8) and hq has somewhere to put a post."""
    root = pathlib.Path(root)
    (root / ".hq").mkdir(parents=True, exist_ok=True)
    (root / ".hq" / ".anchor").write_text("id: test-anchor\n")
    (root / ".git").mkdir(exist_ok=True)


def _seed(p, title, status, blocked_on=None):
    """Seed one open lead into the hq post store.

    `blocked_on` is accepted and dropped: hq's schema has no such field, so the
    gate reports None for it now. That is a real (small) capability loss, kept
    visible here rather than silently by the call site.
    """
    from omx_core.wiki.hq_backend import write_knowledge
    _anchor(p.root)
    return write_knowledge(p.root, now="2026-05-31T10:00:00", title=title, content="c",
                           tags=[], category="decision", confidence="high",
                           status=status)["slug"]


def test_queue_launch_refuses_on_open_hard_gate(tmp_path, capsys, live_hq):
    from omx_core import cli
    p = _p(tmp_path)
    _seed(p, "TAM row rewrite", "needs-apply-before-retrain", "measure first")
    rc = cli.main(["queue-launch", "--predicted-outcome", "test prediction", "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2 and out["refused"] is True
    assert out["open_gates"][0]["slug"].startswith("finding/")
    assert read_pending_launch(p, "run1") is None   # REFUSE wrote NOTHING


def test_queue_launch_ack_gate_allows_and_records(tmp_path, capsys, live_hq):
    from omx_core import cli
    p = _p(tmp_path)
    gate = _seed(p, "TAM row rewrite", "needs-apply-before-retrain")
    rc = cli.main(["queue-launch", "--predicted-outcome", "test prediction", "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g", "--ack-gate", gate])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    # the human-approval artifact now carries the un-applied correction it launched over
    assert out["acknowledged_gates"] == [gate]
    assert read_pending_launch(p, "run1")["acknowledged_gates"] == [gate]


def test_queue_launch_warns_on_soft_lead(tmp_path, capsys, live_hq):
    from omx_core import cli
    p = _p(tmp_path)
    lead = _seed(p, "Command box eval", "needs-experiment")
    rc = cli.main(["queue-launch", "--predicted-outcome", "test prediction", "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g"])
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert rc == 0                                  # soft leads WARN, never REFUSE
    assert out["open_leads"] == [lead]
    assert lead in cap.err


def test_queue_launch_empty_wiki_passes_clean(tmp_path, capsys):
    from omx_core import cli
    rc = cli.main(["queue-launch", "--predicted-outcome", "test prediction", "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "open_leads" not in out and "acknowledged_gates" not in out   # backward-compatible shape


def test_queue_launch_unreadable_store_warns_but_does_not_block(tmp_path, capsys):
    """Replaces the old corrupt-page test: there is no wiki dir to corrupt now,
    and hq owns parsing. The surviving question is the one that matters --
    a store the gate could not read must WARN loudly and still pass, because an
    unreadable store is not an empty one."""
    from omx_core import cli
    rc = cli.main(["queue-launch", "--predicted-outcome", "test prediction",
                   "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g"])
    cap = capsys.readouterr()
    assert rc == 0                       # never blocks a launch
    assert "post store could not be read" in cap.err


def test_queue_pending_launch_records_open_leads_and_acks(tmp_path):
    p = _p(tmp_path)
    queue_pending_launch(p, "run1", proposal_id="x", launch_delta="d", gpu_gate="g",
                         queued_at="2026-07-11T10:00:00+00:00",
                         open_leads=["a.md"], acknowledged_gates=["b.md"], predicted_outcome="test prediction")
    data = read_pending_launch(p, "run1")
    assert data["open_leads"] == ["a.md"]
    assert data["acknowledged_gates"] == ["b.md"]


def test_queue_pending_launch_omits_gate_fields_when_none(tmp_path):
    p = _p(tmp_path)
    queue_pending_launch(p, "run1", proposal_id="x", launch_delta="d", gpu_gate="g",
                         queued_at="2026-07-11T10:00:00+00:00", predicted_outcome="test prediction")
    data = read_pending_launch(p, "run1")
    assert "open_leads" not in data and "acknowledged_gates" not in data


def test_queue_launch_records_wiki_coverage_and_warns_on_an_empty_roster(tmp_path, capsys, live_hq):
    """An empty gate and a gate nobody ever filed against are the same zero.

    albc 2026-08-10: 540 pages, 0 with a blocking status. Every launch that
    round cleared a gate that had never held anything, and the pass read as
    'nothing un-applied'. The denominator has to travel with the verdict.
    """
    from omx_core import cli
    p = _p(tmp_path)
    _seed(p, "some finding nobody gave a status", None)
    rc = cli.main(["queue-launch", "--predicted-outcome", "test prediction",
                   "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g"])
    cap = capsys.readouterr()
    assert rc == 0
    assert read_pending_launch(p, "run1")["wiki_coverage"] == {"pages": 1, "with_status": 0}
    assert "EMPTY roster" in cap.err


def test_queue_launch_does_not_warn_once_the_wiki_is_filed_against(tmp_path, capsys, live_hq):
    from omx_core import cli
    p = _p(tmp_path)
    _seed(p, "a lead someone filed", "needs-experiment")
    rc = cli.main(["queue-launch", "--predicted-outcome", "test prediction",
                   "--root", str(tmp_path), "--run-id", "run1",
                   "--proposal-id", "20260711-100000-x", "--launch-delta", "d",
                   "--gpu-gate", "g"])
    cap = capsys.readouterr()
    assert rc == 0
    assert read_pending_launch(p, "run1")["wiki_coverage"] == {"pages": 1, "with_status": 1}
    assert "EMPTY roster" not in cap.err
