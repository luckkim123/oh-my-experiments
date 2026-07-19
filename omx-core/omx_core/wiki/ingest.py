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
from omx_core.wiki import storage
from omx_core.wiki.types import (
    CATEGORIES,
    CONFIDENCES,
    STATUSES,
    WIKI_SCHEMA_VERSION,
    WikiError,
    WikiPage,
)

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
                     sources: list, quality_score: int | None = None,
                     quality_reasons: tuple = (), status: str | None = None,
                     blocked_on: str | None = None) -> dict:
    """Create or append-merge a wiki page. Returns {action, slug}.

    `status` (optional) is the actionable-status flag; an explicit value must be in
    STATUSES (loud-fail otherwise). On merge, an explicit status/blocked_on WINS and
    None KEEPS the existing value — so a capture session-stub (no status) never
    clobbers a flag, and resolving a lead is a `--status resolved` re-add."""
    if "+" in now or now.endswith("Z"):
        raise WikiError(f"now must be a naive ISO timestamp (no tz offset); got {now!r}")
    if category not in CATEGORIES:
        raise WikiError(f"category {category!r} not in {sorted(CATEGORIES)}")
    if confidence not in CONFIDENCES:
        raise WikiError(f"confidence {confidence!r} not in {list(CONFIDENCES)}")
    if status is not None and status not in STATUSES:
        raise WikiError(f"status {status!r} not in {list(STATUSES)}")
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
                quality_score=quality_score, quality_reasons=list(quality_reasons),
                status=status, blocked_on=blocked_on,
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
            new_qs = quality_score if quality_score is not None else existing.quality_score
            new_qr = list(quality_reasons) if quality_score is not None else existing.quality_reasons
            # explicit-wins / None-keeps: a status-less re-add (capture stub) never
            # clobbers a flag; an explicit --status resolves or re-opens the lead.
            new_status = status if status is not None else existing.status
            new_blocked_on = blocked_on if blocked_on is not None else existing.blocked_on
            appended = existing.content.rstrip() + f"\n\n---\n\n## Update ({now})\n\n{content}\n"
            page = WikiPage(
                slug=slug, title=existing.title,
                tags=merged_tags, created=existing.created, updated=now,
                sources=merged_sources, links=merged_links,
                category=existing.category, confidence=merged_conf,
                schema_version=existing.schema_version,
                quality_score=new_qs, quality_reasons=new_qr,
                status=new_status, blocked_on=new_blocked_on,
                content=appended,
            )
            action = "updated"

        storage.write_page(paths, page, now=now)
        storage.update_index(paths, now=now)
        storage.append_log(paths, now=now, operation="add", pages=[slug],
                           summary=f"{action} {title!r}")
        return {"action": action, "slug": slug}

    return storage.with_wiki_lock(paths, _do)
