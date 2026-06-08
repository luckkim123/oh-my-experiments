"""omx_core.wiki.lint -- audit the wiki (report-only, NEVER auto-fix; W5).

Detects orphan (inbound==0, with fresh-page exemption), stale (updated older
than stale_days), broken-ref (a [[link]] target slug that does not exist),
oversized (content over max_page_size), broken-frontmatter (unparseable),
low-confidence (confidence is 'low'), and contradiction-candidate (a structural
SIGNAL for review, never a verdict -- INV-1). Consumed by `omx wiki lint`, which
exp-loop calls at iteration end. The `now` ISO is injected (no wall clock) so
stale/fresh detection is deterministic.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from omx_core.omx_paths import OmxPaths
from omx_core.wiki.types import WikiError
from omx_core.wiki import storage


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO timestamp to a NAIVE datetime (tzinfo stripped).

    Normalizing to naive keeps the stale-delta total: the wiki writes naive UTC
    (ingest rejects aware `now`), but an externally hand-edited page could carry a
    tz-aware `updated:` field. Stripping tzinfo here means lint audits such a page
    instead of crashing on a naive-vs-aware subtraction (lint stays the robust
    auditor; a wall-clock UTC value compares correctly against the naive `now`)."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed


def _is_fresh(created: str, now_dt, stale_days: int) -> bool:
    """True if `created` is within stale_days/2 of `now` (a new seed page, exempt
    from orphan). An unparseable/absent created is treated as NOT fresh (so old or
    malformed pages can still be flagged). now_dt is the already-parsed naive now;
    None means no time basis -> nothing is fresh."""
    if now_dt is None:
        return False
    created_dt = _parse_iso(created)
    if created_dt is None:
        return False
    return (now_dt - created_dt).days <= stale_days // 2


def _contradiction_candidates(pages: dict) -> list:
    """Structural contradiction SIGNALS (INV-1: candidates only, never a verdict).

    a-1: >=2 pages sharing a tag where EVERY sharing page is confidence 'high'
         -> they may assert conflicting high-confidence conclusions; flag for review.
    a-2: a tag spanning >1 category -> classification drift; flag for review.
    One issue per tag (a-1 takes precedence over a-2 for the same tag)."""
    by_tag: dict = {}
    for page in pages.values():
        for tag in page.tags:
            by_tag.setdefault(tag, []).append(page)

    issues = []
    for tag in sorted(by_tag):
        group = by_tag[tag]
        if len(group) < 2:
            continue
        slugs = sorted(g.slug for g in group)
        # a-1: all sharing pages are high-confidence
        if all(g.confidence == "high" for g in group):
            issues.append({
                "slug": slugs[0], "severity": "info", "type": "contradiction-candidate",
                "message": (f"{len(group)} high-confidence pages share tag {tag!r}; "
                            f"review whether their conclusions conflict: {', '.join(slugs)}"),
            })
            continue
        # a-2: tag spans multiple categories
        cats = sorted({g.category for g in group})
        if len(cats) > 1:
            issues.append({
                "slug": slugs[0], "severity": "info", "type": "contradiction-candidate",
                "message": (f"tag {tag!r} appears across categories {cats}; "
                            f"review for classification drift: {', '.join(slugs)}"),
            })
    return issues


def lint_wiki(paths: OmxPaths, *, now: str, stale_days: int = 30,
              max_page_size: int = 10240) -> dict:
    """Audit every page. Returns {issues:[{slug,severity,type,message}], stats:{...}}."""
    now_dt = _parse_iso(now)
    slugs = storage.list_pages(paths)
    pages = {}
    issues = []

    for slug in slugs:
        try:
            page = storage.read_page(paths, slug)
        except WikiError:
            issues.append({"slug": slug, "severity": "error", "type": "broken-frontmatter",
                           "message": "page has no parseable '---' frontmatter"})
            continue
        if page is not None:
            pages[slug] = page

    valid_slugs = set(pages)
    inbound = {s: 0 for s in valid_slugs}
    for slug, page in pages.items():
        for target in page.links:
            if target in valid_slugs:
                inbound[target] += 1
            else:
                issues.append({"slug": slug, "severity": "warning", "type": "broken-ref",
                               "message": f"link target {target!r} does not exist"})

    for slug, page in pages.items():
        if inbound.get(slug, 0) == 0 and not _is_fresh(page.created, now_dt, stale_days):
            issues.append({"slug": slug, "severity": "info", "type": "orphan",
                           "message": "no page links to this page (inbound==0)"})
        if now_dt is not None:
            updated_dt = _parse_iso(page.updated)
            if updated_dt is not None and (now_dt - updated_dt).days > stale_days:
                issues.append({"slug": slug, "severity": "info", "type": "stale",
                               "message": f"not updated in over {stale_days} days"})
        if len(page.content.encode("utf-8")) > max_page_size:
            issues.append({"slug": slug, "severity": "warning", "type": "oversized",
                           "message": f"content exceeds {max_page_size} bytes"})
        if page.confidence == "low":
            issues.append({"slug": slug, "severity": "info", "type": "low-confidence",
                           "message": "confidence is 'low'; review and strengthen or remove"})

    issues.extend(_contradiction_candidates(pages))

    by_type = dict(Counter(i["type"] for i in issues))
    stats = {"total_pages": len(slugs), "by_type": by_type}
    return {"issues": issues, "stats": stats}
