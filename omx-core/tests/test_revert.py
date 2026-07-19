"""T11: revert-config (#5, spec 2.8). Two-phase git config revert: dry-run by
default, mutation only with --i-approve-revert. Path-scoped allowlist protects
.omx/ (and the resolved root tree inside cwd). The first mutating git call in
omx-core -> the strictest gate (an approval FLAG that cannot be defaulted)."""
import json
import subprocess

import pytest

from omx_core.omx_paths import OmxError, OmxPaths
from omx_core.revert import apply_revert, plan_revert


def _git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, check=True)


def _init_repo(cwd):
    cwd.mkdir(parents=True, exist_ok=True)
    _git(cwd, "init", "-q")
    _git(cwd, "config", "user.email", "t@t.t"); _git(cwd, "config", "user.name", "t")
    (cwd / "config.yaml").write_text("lr: 0.001\n")
    _git(cwd, "add", "config.yaml"); _git(cwd, "commit", "-q", "-m", "base")
    base = subprocess.run(["git", "-C", str(cwd), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    return base


def _p(tmp_path):
    return OmxPaths(root=str(tmp_path))


# --- plan_revert ---

def test_plan_lists_changed_files(tmp_path):
    repo = tmp_path / "proj"
    base = _init_repo(repo)
    (repo / "config.yaml").write_text("lr: 0.5\n")  # working-tree change vs base
    _git(repo, "commit", "-aqm", "bump")
    plan = plan_revert(str(repo), base, protected=[".omx/"])
    assert "config.yaml" in plan["would_revert"]


def test_plan_filters_allowlisted_paths(tmp_path):
    repo = tmp_path / "proj"
    base = _init_repo(repo)
    (repo / ".omx").mkdir()
    (repo / ".omx" / "state.json").write_text("{}")
    (repo / "config.yaml").write_text("lr: 0.5\n")
    _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "bump+omx")
    plan = plan_revert(str(repo), base, protected=[".omx/"])
    assert "config.yaml" in plan["would_revert"]
    assert any(".omx/" in s for s in plan["skipped_allowlist"])
    assert not any(".omx/" in s for s in plan["would_revert"])  # protected, never reverted


def test_plan_non_repo_loud_fails(tmp_path):
    with pytest.raises(OmxError):
        plan_revert(str(tmp_path), "abc", protected=[".omx/"])


def test_plan_filters_unicode_named_allowlisted_paths(tmp_path):
    """git quote-escapes non-ASCII names under --name-only (core.quotepath
    default true); -z must be used so the protected prefix still matches."""
    repo = tmp_path / "proj"
    base = _init_repo(repo)
    (repo / ".omx").mkdir()
    (repo / ".omx" / "한글파일.json").write_text("{}")
    _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "add unicode")
    (repo / ".omx" / "한글파일.json").write_text('{"x": 1}')
    _git(repo, "commit", "-aqm", "bump unicode")
    plan = plan_revert(str(repo), base, protected=[".omx/"])
    assert any("한글파일" in s for s in plan["skipped_allowlist"])
    assert not any("한글파일" in s for s in plan["would_revert"])


def test_plan_filters_quote_bearing_allowlisted_paths(tmp_path):
    repo = tmp_path / "proj"
    base = _init_repo(repo)
    (repo / ".omx").mkdir()
    (repo / ".omx" / 'a "quoted" file.json').write_text("{}")
    _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "add quoted")
    (repo / ".omx" / 'a "quoted" file.json').write_text('{"x": 1}')
    _git(repo, "commit", "-aqm", "bump quoted")
    plan = plan_revert(str(repo), base, protected=[".omx/"])
    assert any("quoted" in s for s in plan["skipped_allowlist"])
    assert not any("quoted" in s for s in plan["would_revert"])


# --- apply_revert ---

def test_apply_reverts_only_planned_paths(tmp_path):
    repo = tmp_path / "proj"
    base = _init_repo(repo)
    (repo / "config.yaml").write_text("lr: 0.5\n")
    _git(repo, "commit", "-aqm", "bump")
    apply_revert(str(repo), base, ["config.yaml"])
    assert (repo / "config.yaml").read_text() == "lr: 0.001\n"  # back to base


def test_apply_revert_failed_checkout_loud_fails(tmp_path):
    # `git checkout <sha> -- <path>` fails (non-zero rc) for a path git has
    # never heard of at that sha. This is the strict gate the module exists
    # for: a failed checkout must raise, never return as if it succeeded.
    repo = tmp_path / "proj"
    base = _init_repo(repo)
    with pytest.raises(OmxError) as ei:
        apply_revert(str(repo), base, ["does/not/exist.txt"])
    msg = str(ei.value)
    assert "git checkout" in msg
    assert base in msg


# --- CLI: dry-run default / approve flag ---

def _seed(tmp_path, base, last_kept=None):
    from omx_core.ledger import seed_ledger
    p = _p(tmp_path)
    seed_ledger(p, "run1", baseline_commit=base, keep_policy="pass_only")
    if last_kept:
        led = json.loads(p.ledger_json("run1").read_text())
        led["last_kept_commit"] = last_kept
        p.ledger_json("run1").write_text(json.dumps(led))


def test_cli_dry_run_is_default(tmp_path, capsys):
    from omx_core import cli
    repo = tmp_path / "proj"
    base = _init_repo(repo)
    (repo / "config.yaml").write_text("lr: 0.5\n"); _git(repo, "commit", "-aqm", "bump")
    _seed(tmp_path, base)
    capsys.readouterr()
    rc = cli.main(["revert-config", "--cwd", str(repo), "--run-id", "run1",
                   "--to", "baseline", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["dry_run"] is True
    assert "config.yaml" in out["would_revert"]
    assert (repo / "config.yaml").read_text() == "lr: 0.5\n"  # NOT mutated (dry-run)


def test_cli_approve_flag_applies(tmp_path, capsys):
    from omx_core import cli
    repo = tmp_path / "proj"
    base = _init_repo(repo)
    (repo / "config.yaml").write_text("lr: 0.5\n"); _git(repo, "commit", "-aqm", "bump")
    _seed(tmp_path, base)
    capsys.readouterr()
    rc = cli.main(["revert-config", "--cwd", str(repo), "--run-id", "run1",
                   "--to", "baseline", "--i-approve-revert", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["dry_run"] is False
    assert "config.yaml" in out["reverted"]
    assert (repo / "config.yaml").read_text() == "lr: 0.001\n"  # mutated back to base


def test_cli_empty_plan_is_noop(tmp_path, capsys):
    from omx_core import cli
    repo = tmp_path / "proj"
    base = _init_repo(repo)  # HEAD == base, nothing changed
    _seed(tmp_path, base)
    capsys.readouterr()
    rc = cli.main(["revert-config", "--cwd", str(repo), "--run-id", "run1",
                   "--to", "baseline", "--i-approve-revert", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["reverted"] == []


def test_cli_to_last_kept_resolves(tmp_path, capsys):
    from omx_core import cli
    repo = tmp_path / "proj"
    base = _init_repo(repo)
    (repo / "config.yaml").write_text("lr: 0.5\n"); _git(repo, "commit", "-aqm", "v2")
    kept = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    (repo / "config.yaml").write_text("lr: 9\n"); _git(repo, "commit", "-aqm", "v3")
    _seed(tmp_path, base, last_kept=kept)
    capsys.readouterr()
    rc = cli.main(["revert-config", "--cwd", str(repo), "--run-id", "run1",
                   "--to", "last-kept", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["dry_run"] is True
    assert "config.yaml" in out["would_revert"]  # diff vs the kept commit


def test_cli_non_repo_cwd_rc2(tmp_path, capsys):
    from omx_core import cli
    _seed(tmp_path, "abc")
    rc = cli.main(["revert-config", "--cwd", str(tmp_path), "--run-id", "run1",
                   "--to", "baseline", "--root", str(tmp_path)])
    assert rc == 2


def test_cli_absent_ledger_rc2(tmp_path, capsys):
    from omx_core import cli
    repo = tmp_path / "proj"
    _init_repo(repo)
    rc = cli.main(["revert-config", "--cwd", str(repo), "--run-id", "ghost",
                   "--to", "baseline", "--root", str(tmp_path)])
    assert rc == 2  # read_run_ledger loud-fails
