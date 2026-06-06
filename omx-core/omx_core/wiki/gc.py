"""omx_core.wiki.gc — execute approved wiki delete/merge (two-phase, git-guarded).

The core carries ZERO semantic judgment (INV-1): it executes an already-approved
proposal file. `parse_gc_proposal` turns the proposal markdown into a GcPlan;
`apply_gc` validates the WHOLE plan (slugs exist, git-tracked, no self-merge)
before mutating anything, so a partial apply is impossible. git tracking is the
recovery path — an untracked target loud-fails rather than becoming unrecoverable.
Wall-clock `now` is injected (no clock here), matching storage/ingest/lint.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from omx_core.omx_paths import OmxPaths, OmxError
from omx_core.wiki import storage
from omx_core.wiki.types import WikiError, WikiPage, WIKI_SCHEMA_VERSION, RESERVED_FILES


def _norm_slug(slug: str) -> str:
    """Normalize a slug to its '<name>.md' form (list_pages/merge compare on this)."""
    return slug if slug.endswith(".md") else f"{slug}.md"


@dataclass
class GcPlan:
    """A parsed, not-yet-validated gc proposal."""
    deletes: list = field(default_factory=list)          # list[str] slug
    merges: list = field(default_factory=list)           # list[dict] {into:str, from:list[str]}

import re

_FM_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


def parse_gc_proposal(raw: str) -> GcPlan:
    """Parse a wiki-gc proposal markdown into a GcPlan. Loud-fail on a missing
    '---' frontmatter block or a `kind` other than 'wiki-gc'. Structural only —
    self-merge and missing-slug checks happen in apply_gc."""
    normalized = raw.replace("\r\n", "\n")
    m = _FM_RE.match(normalized)
    if not m:
        raise WikiError("gc proposal has no '---' frontmatter block")
    fm, body = m.group(1), m.group(2)
    kind = None
    for line in fm.split("\n"):
        if line.startswith("kind:"):
            kind = line.split(":", 1)[1].strip()
            break
    if kind != "wiki-gc":
        raise WikiError(f"gc proposal kind must be 'wiki-gc', got {kind!r}")

    deletes: list = []
    merges: list = []
    section = None
    current = None  # the in-progress merge dict
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped == "## DELETE":
            section, current = "delete", None
            continue
        if stripped == "## MERGE":
            section, current = "merge", None
            continue
        if section == "delete":
            mm = re.match(r"-\s*slug:\s*(\S+)", stripped)
            if mm:
                deletes.append(_norm_slug(mm.group(1)))
        elif section == "merge":
            mi = re.match(r"-\s*into:\s*(\S+)", stripped)
            if mi:
                current = {"into": _norm_slug(mi.group(1)), "from": []}
                merges.append(current)
                continue
            mf = re.match(r"-\s*(\S+)", stripped)
            # an indented "- <slug>" under a "from:" belongs to the current merge;
            # the literal "from:" line itself has no leading "-", so it's skipped
            if current is not None and mf and not stripped.startswith("from:") \
                    and "into:" not in stripped and "reason:" not in stripped:
                current["from"].append(_norm_slug(mf.group(1)))
    return GcPlan(deletes=deletes, merges=merges)

import subprocess
from pathlib import Path


def is_git_tracked(repo_root, file_path) -> bool:
    """True iff `file_path` is a git-tracked file under `repo_root`. No git, no
    repo, or an untracked path all return False (never raises) — the caller turns
    a False into the loud-fail. This is the recovery guarantee: gc-apply refuses
    to delete anything git cannot restore."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", str(Path(file_path).resolve())],
            capture_output=True, text=True, check=False,
        )
    except (FileNotFoundError, OSError):
        return False
    return proc.returncode == 0


def delete_page(paths: OmxPaths, slug: str) -> None:
    """Unlink one wiki page. Caller MUST hold the wiki lock and is responsible for
    update_index/append_log afterwards (apply_gc batches these). Loud-fail on a
    reserved file or an absent page. No git check here — apply_gc validates the
    whole plan against git before any mutation."""
    norm = _norm_slug(slug)
    if norm in RESERVED_FILES:
        raise WikiError(f"cannot delete reserved file {norm!r}")
    fp = paths.wiki_page(norm[:-3])  # validates token -> blocks traversal
    if not fp.exists():
        raise WikiError(f"cannot delete absent page {norm!r}")
    fp.unlink()
