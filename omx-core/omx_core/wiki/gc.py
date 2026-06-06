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
from omx_core.wiki.types import WikiError, WikiPage, WIKI_SCHEMA_VERSION


def _norm_slug(slug: str) -> str:
    """Normalize a slug to its '<name>.md' form (list_pages/merge compare on this)."""
    return slug if slug.endswith(".md") else f"{slug}.md"


@dataclass
class GcPlan:
    """A parsed, not-yet-validated gc proposal."""
    deletes: list = field(default_factory=list)          # list[str] slug
    merges: list = field(default_factory=list)           # list[dict] {into:str, from:list[str]}
