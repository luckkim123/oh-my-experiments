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

from omx_core.omx_paths import OmxPaths
from omx_core.wiki import storage
from omx_core.wiki.types import WikiError, WikiPage, RESERVED_FILES


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

def suggest_from_lint(lint_res: dict) -> dict:
    """Turn a lint result into REVIEW-ONLY gc delete candidates (INV-1: candidates,
    not a proposal; nothing is written or deleted). ONLY 'orphan' (info) slugs are
    suggested for deletion — stale is 'old' not 'useless', and error/warning types
    (broken-ref/oversized/broken-frontmatter) are fix-in-place, not delete. Returns
    {delete_candidates: [slug...], proposal_skeleton: <editable wiki-gc proposal>}.
    The human copies/edits the skeleton; gc-apply (git-guarded) is the only executor."""
    # an open lead is typically inbound==0 (nothing links to it yet — that's WHY it is a
    # backlog page), so exempt any slug lint flagged as open-lead from delete suggestions.
    open_lead_slugs = {
        i["slug"] for i in lint_res.get("issues", [])
        if i.get("type") == "open-lead"
    }
    candidates = sorted({
        i["slug"] for i in lint_res.get("issues", [])
        if i.get("type") == "orphan" and i["slug"] not in open_lead_slugs
    })
    delete_lines = "\n".join(f"- slug: {s}" for s in candidates) or "# (none)"
    skeleton = (
        "---\n"
        "kind: wiki-gc\n"
        "---\n\n"
        "## DELETE\n\n"
        f"{delete_lines}\n\n"
        "## MERGE\n\n"
        "# (add `- into: <survivor>` then indented `- <source>` lines to merge instead of delete)\n"
    )
    return {"delete_candidates": candidates, "proposal_skeleton": skeleton}


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


_CONF_RANK = {"high": 3, "medium": 2, "low": 1}
#: Most-open-wins on merge (mirrors _CONF_RANK): a folded duplicate must never
#: silently disarm a HARD gate. None(0) < resolved(1) < needs-experiment(2)
#: < needs-apply-before-retrain(3).
_STATUS_RANK = {None: 0, "resolved": 1, "needs-experiment": 2, "needs-apply-before-retrain": 3}


def merge_pages(paths: OmxPaths, *, into: str, from_slugs: list, now: str) -> None:
    """Fold each `from` page into the `into` survivor (lossless), then delete the
    `from` pages. Tags union, sources append, links union, confidence max, status
    most-open-wins, blocked_on survivor-first; each source body is appended as a
    '## Merged from <slug> (<now>)' section. Caller holds the lock and does
    update_index/append_log. Loud-fail on self-merge or an absent page."""
    into_norm = _norm_slug(into)
    froms = [_norm_slug(s) for s in from_slugs]
    if into_norm in froms:
        raise WikiError(f"self-merge: {into_norm!r} is both survivor and source")

    survivor = storage.read_page(paths, into_norm)
    if survivor is None:
        raise WikiError(f"merge survivor {into_norm!r} does not exist")

    tags = list(survivor.tags)
    sources = list(survivor.sources)
    links = list(survivor.links)
    confidence = survivor.confidence
    status = survivor.status
    blocked_on = survivor.blocked_on
    content = survivor.content.rstrip()

    for fslug in froms:
        src = storage.read_page(paths, fslug)
        if src is None:
            raise WikiError(f"merge source {fslug!r} does not exist")
        for t in src.tags:
            if t not in tags:
                tags.append(t)
        for s in src.sources:
            if s not in sources:
                sources.append(s)
        for l in src.links:
            if l not in links:
                links.append(l)
        if _CONF_RANK.get(src.confidence, 2) > _CONF_RANK.get(confidence, 2):
            confidence = src.confidence
        if _STATUS_RANK.get(src.status, 0) > _STATUS_RANK.get(status, 0):
            status = src.status
        if blocked_on is None and src.blocked_on is not None:
            blocked_on = src.blocked_on   # survivor-first, else first source that set it
        content += f"\n\n---\n\n## Merged from {fslug} ({now})\n\n{src.content.strip()}\n"

    merged = WikiPage(
        slug=into_norm, title=survivor.title, tags=tags,
        created=survivor.created, updated=now, sources=sources, links=links,
        category=survivor.category, confidence=confidence,
        schema_version=survivor.schema_version,
        quality_score=survivor.quality_score,
        quality_reasons=list(survivor.quality_reasons),
        status=status, blocked_on=blocked_on, content=content,
    )
    storage.write_page(paths, merged, now=now)
    for fslug in froms:
        delete_page(paths, fslug)


def apply_gc(paths: OmxPaths, plan: GcPlan, *, now: str, repo_root,
             git_check=is_git_tracked) -> dict:
    """Two-phase apply. Phase 1 validates the WHOLE plan (every slug exists and is
    git-tracked; no self-merge) and mutates nothing on failure. Phase 2, under the
    wiki lock, runs deletes then merges, then regenerates the index and logs. An
    empty plan is a no-op (no lock). git_check is injected for testing; the CLI
    passes is_git_tracked. The validate-first design makes a partial apply
    impossible — the recovery guarantee plus atomicity of intent."""
    if not plan.deletes and not plan.merges:
        return {"deleted": [], "merged": []}

    # ---- phase 1: validate everything, touch nothing ----
    def _require(slug: str) -> None:
        norm = _norm_slug(slug)
        fp = paths.wiki_page(norm[:-3])
        if not fp.exists():
            raise WikiError(f"gc target {norm!r} does not exist")
        if not git_check(repo_root, fp):
            raise WikiError(
                f"wiki gc-apply requires git tracking for recovery; {norm!r} is untracked")

    for slug in plan.deletes:
        _require(slug)
    for merge in plan.merges:
        into_norm = _norm_slug(merge["into"])
        froms = [_norm_slug(s) for s in merge["from"]]
        if into_norm in froms:
            raise WikiError(f"self-merge: {into_norm!r} is both survivor and source")
        _require(into_norm)
        for f in froms:
            _require(f)

    # ---- phase 2: execute under the lock ----
    def _do() -> dict:
        for slug in plan.deletes:
            delete_page(paths, slug)
        for merge in plan.merges:
            merge_pages(paths, into=merge["into"], from_slugs=merge["from"], now=now)
        storage.update_index(paths, now=now)
        n_del = len(plan.deletes)
        n_merge = sum(len(m["from"]) for m in plan.merges)
        storage.append_log(paths, now=now, operation="gc-apply",
                           pages=[_norm_slug(s) for s in plan.deletes],
                           summary=f"deleted {n_del}, merged {n_merge} source(s)")
        return {
            "deleted": [_norm_slug(s) for s in plan.deletes],
            "merged": [{"into": _norm_slug(m["into"]),
                        "from": [_norm_slug(s) for s in m["from"]]} for m in plan.merges],
        }

    return storage.with_wiki_lock(paths, _do)
