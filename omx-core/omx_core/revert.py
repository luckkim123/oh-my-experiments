"""omx_core.revert — config revert via git (#5, spec 2.8, B6 'config->git').

The FIRST mutating git call in omx-core (today's git sites are read-only:
root._git check_output-wrapped, gc.is_git_tracked run(check=False)), so it
takes the strictest gate: validate the whole plan before mutating (two-phase),
and an approval FLAG that cannot be defaulted (the verb layer enforces it).
NEVER called from a hook or a loop branch — the skill surfaces the dry-run and
the human approves (D4/never-auto-git)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from omx_core.omx_paths import OmxError


def _run_git(cwd, args) -> subprocess.CompletedProcess:
    """git in `cwd`, never raising on a non-zero rc (the gc.py idiom). OSError
    (no git) converts to a loud-fail at the caller."""
    try:
        return subprocess.run(["git", "-C", str(cwd), *args],
                              capture_output=True, text=True, check=False)
    except (FileNotFoundError, OSError) as e:
        raise OmxError(f"git unavailable for revert in {cwd!r}: {e}") from e


def _is_protected(path: str, protected) -> bool:
    """True if the repo-relative `path` falls under any protected prefix. Prefix
    match on '/'-normalized components (not a basename match) so an unrelated
    file that merely shares a name is not over-protected (critic gap)."""
    norm = path.replace("\\", "/")
    for prefix in protected:
        pre = prefix.replace("\\", "/").rstrip("/") + "/"
        if norm == prefix.rstrip("/") or norm.startswith(pre):
            return True
    return False


def plan_revert(cwd, sha, protected) -> dict:
    """Return the two-phase plan: {would_revert, skipped_allowlist}. Loud-fail
    (OmxError) if `cwd` is not a git repo or `sha` does not resolve. `protected`
    is the list of repo-relative prefixes NEVER reverted (.omx/, plus the
    resolved root tree when it lies inside cwd)."""
    cwd = Path(cwd)
    # not a repo, or sha unresolvable -> loud-fail
    top = _run_git(cwd, ["rev-parse", "--show-toplevel"])
    if top.returncode != 0:
        raise OmxError(f"--cwd {cwd!r} is not a git repository")
    resolved = _run_git(cwd, ["rev-parse", "--verify", f"{sha}^{{commit}}"])
    if resolved.returncode != 0:
        raise OmxError(f"revert target {sha!r} does not resolve to a commit in {cwd!r}")
    # -z: NUL-delimited output, which git documents as disabling path quoting
    # regardless of core.quotepath -- avoids the quote/octal-escape mangling
    # that '--name-only' alone applies to non-ASCII or quote-bearing paths.
    diff = _run_git(cwd, ["diff", "--name-only", "-z", sha])
    if diff.returncode != 0:
        raise OmxError(
            f"git diff against {sha!r} failed in {cwd!r}: {diff.stderr.strip()}")
    changed = [p for p in diff.stdout.split("\0") if p.strip()]
    would_revert, skipped = [], []
    for path in changed:
        (skipped if _is_protected(path, protected) else would_revert).append(path)
    return {"would_revert": sorted(would_revert), "skipped_allowlist": sorted(skipped)}


def apply_revert(cwd, sha, paths) -> None:
    """git checkout <sha> -- <paths> (loud by design: returncode checked,
    OmxError raised on failure). `paths` is the validated would_revert list
    from plan_revert; an empty list is a no-op the caller handles before
    calling this."""
    if not paths:
        return
    proc = _run_git(cwd, ["checkout", sha, "--", *paths])
    if proc.returncode != 0:
        raise OmxError(
            f"git checkout {sha!r} failed in {cwd!r}: {proc.stderr.strip()}")
