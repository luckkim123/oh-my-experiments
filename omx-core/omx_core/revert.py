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


def resolve_git_toplevel(cwd) -> Path:
    """The git top-level for `cwd` (loud-fail OmxError if `cwd` is not a git
    repository). This is what `git diff --name-only`/`git checkout` actually
    match paths against, REGARDLESS of which subdirectory `-C cwd` points at
    — `cwd` itself must never be used as the relative-path base for building
    a protected-paths allowlist (store-spec §7: a nested anchor, e.g.
    `<repo>/some/sub/project/.hq`, is the normal case, not an edge case)."""
    top = _run_git(cwd, ["rev-parse", "--show-toplevel"])
    if top.returncode != 0:
        raise OmxError(f"--cwd {cwd!r} is not a git repository")
    return Path(top.stdout.strip()).resolve()


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
    is the list of repo-relative prefixes NEVER reverted — the caller (cli.py)
    builds it via `resolve_git_toplevel()` so it covers BOTH `.hq/` and legacy
    `.omx/`, expressed relative to the git top-level rather than `cwd`."""
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
    from plan_revert — repo-relative to the git TOP-LEVEL, since that is
    what `git diff --name-only` always emits regardless of `-C`. `git
    checkout`'s pathspec is the OPPOSITE convention: resolved relative to
    `-C` itself, never the top-level. So this runs `-C <top-level>`, not
    `-C cwd` — a `cwd` that is merely some directory inside the repo (not
    necessarily the top-level; a nested anchor is the normal case) would
    otherwise fail to find every path plan_revert just found. An empty
    list is a no-op the caller handles before calling this."""
    if not paths:
        return
    top = resolve_git_toplevel(cwd)
    proc = _run_git(top, ["checkout", sha, "--", *paths])
    if proc.returncode != 0:
        raise OmxError(
            f"git checkout {sha!r} failed in {cwd!r}: {proc.stderr.strip()}")
