"""omx_core.wiki.types — wiki page schema (data only, no logic).

Re-implements OMC's wiki page shape in Python (pattern, not import). All field
values are runtime inputs — the core carries ZERO domain knowledge (INV-1).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from omx_core.omx_paths import OmxError

#: Bump on a breaking frontmatter change.
WIKI_SCHEMA_VERSION = 1

#: Domain-neutral page categories (INV-1: no experiment-specific names).
CATEGORIES = frozenset({
    "architecture", "decision", "pattern", "debugging",
    "environment", "session-log", "reference", "convention",
})

#: Confidence levels, ordered high -> low (rank index = lower is more confident).
CONFIDENCES = ("high", "medium", "low")

#: Files in the wiki dir that are NOT pages (auto-maintained); never writable as a page.
RESERVED_FILES = frozenset({"index.md", "log.md"})


class WikiError(OmxError):
    """Any wiki loud-fail (bad category/confidence, reserved-file write, lock
    timeout, traversal). Subclass of OmxError so callers catch one base."""


@dataclass(frozen=True)
class WikiPage:
    """One wiki page: frontmatter fields + markdown content + its filename slug."""
    slug: str                      # filename incl. '.md' (e.g. "my-page.md")
    title: str
    tags: list[str] = field(default_factory=list)
    created: str = ""
    updated: str = ""
    sources: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    category: str = "reference"
    confidence: str = "medium"
    schema_version: int = WIKI_SCHEMA_VERSION
    content: str = ""
