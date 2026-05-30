"""omx_core.wiki.ingest — write knowledge into the wiki (append-merge, never replace).

ingest_knowledge takes ALREADY-DECIDED fields ({title, content, tags, category,
confidence, sources}) — choosing what to record and how to categorize it is the
SKILL's (Claude's) job (W2). On a slug collision the page is MERGED, never
overwritten: tags union, sources append, confidence max, content appended as a
new timestamped section. This is INV-2: knowledge accrues without loss.
"""
from __future__ import annotations

import re

from omx_core.omx_paths import OmxPaths
from omx_core.wiki.types import (
    WikiError,
    WikiPage,
    CATEGORIES,
    CONFIDENCES,
    WIKI_SCHEMA_VERSION,
)
from omx_core.wiki import storage

_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_CONF_RANK = {"high": 3, "medium": 2, "low": 1}


def _extract_links(content: str) -> list[str]:
    seen = []
    for m in _LINK_RE.findall(content):
        slug = storage.title_to_slug(m.strip())
        if slug not in seen:
            seen.append(slug)
    return seen


def ingest_knowledge(paths: OmxPaths, *, now: str, title: str, content: str,
                     tags: list, category: str, confidence: str,
                     sources: list) -> dict:
    """Create or append-merge a wiki page. Returns {action, slug}."""
    if category not in CATEGORIES:
        raise WikiError(f"category {category!r} not in {sorted(CATEGORIES)}")
    if confidence not in CONFIDENCES:
        raise WikiError(f"confidence {confidence!r} not in {list(CONFIDENCES)}")
    if not title.strip():
        raise WikiError("wiki page title must be non-empty")

    slug = storage.title_to_slug(title)

    def _do() -> dict:
        existing = storage.read_page(paths, slug)
        if existing is None:
            page = WikiPage(
                slug=slug, title=title,
                tags=list(dict.fromkeys(tags)),
                created=now, updated=now,
                sources=list(dict.fromkeys(sources)),
                links=_extract_links(content),
                category=category, confidence=confidence,
                schema_version=WIKI_SCHEMA_VERSION,
                content=f"\n# {title}\n\n{content}\n",
            )
            action = "created"
        else:
            merged_tags = list(dict.fromkeys([*existing.tags, *tags]))
            merged_sources = list(dict.fromkeys([*existing.sources, *sources]))
            merged_links = list(dict.fromkeys([*existing.links, *_extract_links(content)]))
            # both confidences are pre-validated against CONFIDENCES; .get fallback is unreachable
            if _CONF_RANK.get(confidence, 2) >= _CONF_RANK.get(existing.confidence, 2):
                merged_conf = confidence
            else:
                merged_conf = existing.confidence
            appended = existing.content.rstrip() + f"\n\n---\n\n## Update ({now})\n\n{content}\n"
            page = WikiPage(
                slug=slug, title=existing.title,
                tags=merged_tags, created=existing.created, updated=now,
                sources=merged_sources, links=merged_links,
                category=existing.category, confidence=merged_conf,
                schema_version=existing.schema_version, content=appended,
            )
            action = "updated"

        storage.write_page(paths, page, now=now)
        storage.update_index(paths, now=now)
        storage.append_log(paths, now=now, operation="add", pages=[slug],
                           summary=f"{action} {title!r}")
        return {"action": action, "slug": slug}

    return storage.with_wiki_lock(paths, _do)
