"""omx_core.wiki.lint -- audit the wiki (report-only, NEVER auto-fix; W5).

Detects orphan (no inbound/outbound links), stale (updated older than
stale_days), broken-ref (a [[link]] target slug that does not exist),
oversized (content over max_page_size), and broken-frontmatter (unparseable).
Consumed by `omx wiki lint`, which exp-loop calls at iteration end. The `now`
ISO is injected (no wall clock) so stale detection is deterministic.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from omx_core.omx_paths import OmxPaths
from omx_core.wiki.types import WikiError
from omx_core.wiki import storage


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


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
        if not page.links and inbound.get(slug, 0) == 0:
            issues.append({"slug": slug, "severity": "info", "type": "orphan",
                           "message": "page has no inbound or outbound links"})
        if now_dt is not None:
            updated_dt = _parse_iso(page.updated)
            if updated_dt is not None and (now_dt - updated_dt).days > stale_days:
                issues.append({"slug": slug, "severity": "info", "type": "stale",
                               "message": f"not updated in over {stale_days} days"})
        if len(page.content.encode("utf-8")) > max_page_size:
            issues.append({"slug": slug, "severity": "warning", "type": "oversized",
                           "message": f"content exceeds {max_page_size} bytes"})

    by_type = dict(Counter(i["type"] for i in issues))
    stats = {"total_pages": len(slugs), "by_type": by_type}
    return {"issues": issues, "stats": stats}
