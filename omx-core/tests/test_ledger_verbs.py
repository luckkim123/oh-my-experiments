"""T7: run-ledger write verbs (#25, D-R4-2). run-seed wraps seed_ledger (once);
run-record wraps record_iteration + asserts the run lease by session id + runs
the git-ancestry staleness check. Tests build a tmp git repo with subprocess."""
import json
import subprocess

import pytest

from omx_core.lock import acquire_run_lease
from omx_core.omx_paths import OmxPaths


def _p(tmp_path):
    return OmxPaths(root=str(tmp_path))


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, check=True)


def _init_repo(cwd):
    cwd.mkdir(parents=True, exist_ok=True)
    _git(cwd, "init", "-q")
    _git(cwd, "config", "user.email", "t@t.t")
    _git(cwd, "config", "user.name", "t")
    (cwd / "f.txt").write_text("base\n")
    _git(cwd, "add", "f.txt")
    _git(cwd, "commit", "-q", "-m", "base")
    return subprocess.run(["git", "-C", str(cwd), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def _commit(cwd, text):
    (cwd / "f.txt").write_text(text)
    _git(cwd, "add", "f.txt")
    _git(cwd, "commit", "-q", "-m", text)
    return subprocess.run(["git", "-C", str(cwd), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


# --- run-seed ---

def test_run_seed_creates_ledger(tmp_path, capsys):
    from omx_core import cli
    rc = cli.main(["run-seed", "--run-id", "run1", "--baseline-commit", "abc123",
                   "--keep-policy", "pass_only", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["baseline_commit"] == "abc123"
    led = json.loads(_p(tmp_path).ledger_json("run1").read_text())
    assert led["baseline_commit"] == "abc123" and led["keep_policy"] == "pass_only"


def test_run_seed_twice_loud_fails(tmp_path, capsys):
    from omx_core import cli
    cli.main(["run-seed", "--run-id", "run1", "--baseline-commit", "abc",
              "--keep-policy", "pass_only", "--root", str(tmp_path)])
    capsys.readouterr()
    rc = cli.main(["run-seed", "--run-id", "run1", "--baseline-commit", "def",
                   "--keep-policy", "pass_only", "--root", str(tmp_path)])
    assert rc == 2
    assert "already" in capsys.readouterr().err.lower()


# --- run-record: basic round-trip (no lease, no cwd) ---

def test_run_record_appends_entry_and_prints_pointer(tmp_path, capsys):
    from omx_core import cli
    cli.main(["run-seed", "--run-id", "run1", "--baseline-commit", "base",
              "--keep-policy", "pass_only", "--root", str(tmp_path)])
    capsys.readouterr()
    rc = cli.main(["run-record", "--run-id", "run1", "--iteration", "1",
                   "--decision", "keep", "--candidate-checkpoint", "/ckpt/1",
                   "--candidate-commit", "cand1", "--description", "first",
                   "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["last_kept_commit"] == "cand1"
    assert out["last_kept_checkpoint"] == "/ckpt/1"
    assert out["entry"]["iteration"] == 1 and out["entry"]["decision"] == "keep"


# --- run-record: lease assertion matrix ---

def test_run_record_wrong_session_rc2(tmp_path, capsys):
    from omx_core import cli
    p = _p(tmp_path)
    cli.main(["run-seed", "--run-id", "run1", "--baseline-commit", "base",
              "--keep-policy", "pass_only", "--root", str(tmp_path)])
    acquire_run_lease(p, "run1", session_id="owner", now_iso="2026-07-11T10:00:00+00:00")
    capsys.readouterr()
    rc = cli.main(["run-record", "--run-id", "run1", "--iteration", "1",
                   "--decision", "discard", "--candidate-checkpoint", "/c",
                   "--candidate-commit", "cand1", "--description", "d",
                   "--session-id", "intruder", "--root", str(tmp_path)])
    assert rc == 2
    assert "owned by loop session" in capsys.readouterr().err


def test_run_record_matching_session_ok(tmp_path, capsys):
    from omx_core import cli
    p = _p(tmp_path)
    cli.main(["run-seed", "--run-id", "run1", "--baseline-commit", "base",
              "--keep-policy", "pass_only", "--root", str(tmp_path)])
    acquire_run_lease(p, "run1", session_id="owner", now_iso="2026-07-11T10:00:00+00:00")
    capsys.readouterr()
    rc = cli.main(["run-record", "--run-id", "run1", "--iteration", "1",
                   "--decision", "discard", "--candidate-checkpoint", "/c",
                   "--candidate-commit", "cand1", "--description", "d",
                   "--session-id", "owner", "--root", str(tmp_path)])
    assert rc == 0


def test_run_record_no_session_flag_warns_but_proceeds(tmp_path, capsys):
    from omx_core import cli
    p = _p(tmp_path)
    cli.main(["run-seed", "--run-id", "run1", "--baseline-commit", "base",
              "--keep-policy", "pass_only", "--root", str(tmp_path)])
    acquire_run_lease(p, "run1", session_id="owner", now_iso="2026-07-11T10:00:00+00:00")
    capsys.readouterr()
    rc = cli.main(["run-record", "--run-id", "run1", "--iteration", "1",
                   "--decision", "discard", "--candidate-checkpoint", "/c",
                   "--candidate-commit", "cand1", "--description", "d",
                   "--root", str(tmp_path)])
    cap = capsys.readouterr()
    assert rc == 0
    assert "unverifiable" in cap.err.lower() or "no --session-id" in cap.err.lower()


def test_run_record_no_lease_proceeds_silently(tmp_path, capsys):
    from omx_core import cli
    cli.main(["run-seed", "--run-id", "run1", "--baseline-commit", "base",
              "--keep-policy", "pass_only", "--root", str(tmp_path)])
    capsys.readouterr()
    rc = cli.main(["run-record", "--run-id", "run1", "--iteration", "1",
                   "--decision", "discard", "--candidate-checkpoint", "/c",
                   "--candidate-commit", "cand1", "--description", "d",
                   "--session-id", "whoever", "--root", str(tmp_path)])
    assert rc == 0  # no lease -> single-shot record outside a loop is legitimate


# --- run-record: ancestry staleness matrix (tmp git repo) ---

def test_staleness_ancestor_passes(tmp_path, capsys):
    from omx_core import cli
    repo = tmp_path / "proj"
    base = _init_repo(repo)
    cand = _commit(repo, "candidate")  # base is an ANCESTOR of cand
    cli.main(["run-seed", "--run-id", "run1", "--baseline-commit", base,
              "--keep-policy", "pass_only", "--root", str(tmp_path)])
    capsys.readouterr()
    rc = cli.main(["run-record", "--run-id", "run1", "--iteration", "1",
                   "--decision", "keep", "--candidate-checkpoint", "/c",
                   "--candidate-commit", cand, "--description", "d",
                   "--cwd", str(repo), "--root", str(tmp_path)])
    assert rc == 0


def test_staleness_non_ancestor_rc2(tmp_path, capsys):
    from omx_core import cli
    repo = tmp_path / "proj"
    base = _init_repo(repo)
    # diverge: a second root-less branch commit that is NOT a descendant of base
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--orphan", "other"],
                   check=True)
    (repo / "g.txt").write_text("x")
    _git(repo, "add", "g.txt")
    _git(repo, "commit", "-q", "-m", "orphan")
    diverged = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    cli.main(["run-seed", "--run-id", "run1", "--baseline-commit", base,
              "--keep-policy", "pass_only", "--root", str(tmp_path)])
    capsys.readouterr()
    rc = cli.main(["run-record", "--run-id", "run1", "--iteration", "1",
                   "--decision", "keep", "--candidate-checkpoint", "/c",
                   "--candidate-commit", diverged, "--description", "d",
                   "--cwd", str(repo), "--root", str(tmp_path)])
    assert rc == 2
    assert "ancestor" in capsys.readouterr().err.lower()


def test_staleness_no_cwd_warns_and_skips(tmp_path, capsys):
    from omx_core import cli
    cli.main(["run-seed", "--run-id", "run1", "--baseline-commit", "base",
              "--keep-policy", "pass_only", "--root", str(tmp_path)])
    capsys.readouterr()
    rc = cli.main(["run-record", "--run-id", "run1", "--iteration", "1",
                   "--decision", "keep", "--candidate-checkpoint", "/c",
                   "--candidate-commit", "cand", "--description", "d",
                   "--root", str(tmp_path)])  # no --cwd
    assert rc == 0
    assert "staleness check skipped" in capsys.readouterr().err.lower()


def test_staleness_escape_flag_skips(tmp_path, capsys):
    from omx_core import cli
    repo = tmp_path / "proj"
    base = _init_repo(repo)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--orphan", "other"],
                   check=True)
    (repo / "g.txt").write_text("x")
    _git(repo, "add", "g.txt"); _git(repo, "commit", "-q", "-m", "orphan")
    diverged = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    cli.main(["run-seed", "--run-id", "run1", "--baseline-commit", base,
              "--keep-policy", "pass_only", "--root", str(tmp_path)])
    capsys.readouterr()
    rc = cli.main(["run-record", "--run-id", "run1", "--iteration", "1",
                   "--decision", "keep", "--candidate-checkpoint", "/c",
                   "--candidate-commit", diverged, "--description", "d",
                   "--cwd", str(repo), "--no-staleness-check", "--root", str(tmp_path)])
    assert rc == 0  # escape hatch overrides the non-ancestor loud-fail


def test_run_record_embeds_eval_json(tmp_path, capsys):
    from omx_core import cli
    cli.main(["run-seed", "--run-id", "run1", "--baseline-commit", "base",
              "--keep-policy", "pass_only", "--root", str(tmp_path)])
    eval_out = tmp_path / "eval.json"
    eval_out.write_text(json.dumps({
        "status": "pass", "pass": True, "score": 1.0,
        "decision": {"decision": "keep", "keep": True,
                     "evaluator": {"status": "pass", "pass": True, "score": 1.0},
                     "decision_reason": "score improved", "notes": []}}))
    capsys.readouterr()
    rc = cli.main(["run-record", "--run-id", "run1", "--iteration", "1",
                   "--decision", "keep", "--candidate-checkpoint", "/c",
                   "--candidate-commit", "cand1", "--description", "d",
                   "--eval-json", str(eval_out), "--root", str(tmp_path)])
    assert rc == 0
    led = json.loads(_p(tmp_path).ledger_json("run1").read_text())
    assert led["entries"][0]["evaluator"]["status"] == "pass"


def test_run_record_eval_json_missing_decision_reason_rc2(tmp_path, capsys):
    # a schema-drifted eval doc with 'decision' but no 'decision_reason' must
    # loud-fail through SystemExit -> rc 2, not an uncaught KeyError at rc 1
    # (record_iteration reads decision["decision_reason"] unconditionally).
    from omx_core import cli
    cli.main(["run-seed", "--run-id", "run1", "--baseline-commit", "base",
              "--keep-policy", "pass_only", "--root", str(tmp_path)])
    eval_out = tmp_path / "eval.json"
    eval_out.write_text(json.dumps({
        "decision": {"decision": "keep", "keep": True}}))  # no decision_reason
    capsys.readouterr()
    rc = cli.main(["run-record", "--run-id", "run1", "--iteration", "1",
                   "--decision", "keep", "--candidate-checkpoint", "/c",
                   "--candidate-commit", "cand1", "--description", "d",
                   "--eval-json", str(eval_out), "--root", str(tmp_path)])
    assert rc == 2
    assert "decision_reason" in capsys.readouterr().err


# --- run-seed: crash-recovery (a killed seed leaves baseline_commit=None) ---

def test_run_seed_retries_after_placeholder_crash(tmp_path, capsys):
    # simulate a process killed between the O_CREAT|O_EXCL placeholder write
    # and the seed_ledger call: ledger.json exists but baseline_commit is None.
    # A retry must be able to actually seed it, not be permanently locked out.
    from omx_core.ledger import _default_ledger
    p = _p(tmp_path)
    target = p.ledger_json("run1")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_default_ledger()))
    from omx_core import cli
    rc = cli.main(["run-seed", "--run-id", "run1", "--baseline-commit", "abc123",
                   "--keep-policy", "pass_only", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["baseline_commit"] == "abc123"
