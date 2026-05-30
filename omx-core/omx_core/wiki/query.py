"""omx_core.wiki.query — keyword + tag search (NO vector embeddings — hard constraint).

tokenize handles Latin/digits plus CJK bi-grams (so Korean research notes are
searchable — INV-2). Scoring: tag match > title match > content match (OMC
weights). A page with broken frontmatter is SKIPPED but reported in
`corrupt_pages` (W8: visible-skip, never silent, never whole-fail).
"""
from __future__ import annotations

import re

from omx_core.omx_paths import OmxPaths
from omx_core.wiki.types import WikiError
from omx_core.wiki import storage

_LATIN = re.compile(r"[a-z0-9À-ɏ]+")
_CJK = re.compile(r"[぀-ゟ゠-ヿ一-鿿가-힯]+")


def tokenize(text: str) -> list[str]:
    """Lowercase tokens: Latin/digit words + CJK singletons + CJK bigrams."""
    lower = text.lower()
    tokens = list(_LATIN.findall(lower))
    for seg in _CJK.findall(lower):
        for ch in seg:
            tokens.append(ch)
        for i in range(len(seg) - 1):
            tokens.append(seg[i:i + 2])
    return tokens


def query_wiki(paths: OmxPaths, *, now: str, text: str, tags: list | None = None,
               category: str | None = None, limit: int = 20) -> dict:
    """Search the wiki. Returns {n_matches, n_returned, matches:[...], corrupt_pages:[...]}.

    n_matches is the TOTAL count of pages that scored > 0; n_returned is how many
    are present in `matches` after the limit cap. Skills use n_matches to judge
    coverage, so it must reflect the full matched set, not the truncated slice.

    The injected `now` is used ONLY to timestamp the advisory query-log entry; it
    is not part of scoring.

    The query is logged via append_log without holding the wiki lock; the query
    log is advisory (pages are the knowledge), so an interleaved log line under
    concurrent queries is acceptable.
    """
    query_lower = text.lower()
    terms = tokenize(text)
    matches = []
    corrupt = []

    for slug in storage.list_pages(paths):
        try:
            page = storage.read_page(paths, slug)
        except WikiError:
            corrupt.append(slug)
            continue
        if page is None:
            continue
        if category is not None and page.category != category:
            continue

        score = 0
        snippet = ""

        if tags:
            overlap = [t for t in tags if any(pt.lower() == t.lower() for pt in page.tags)]
            score += len(overlap) * 3
        for term in terms:
            if any(term in pt.lower() for pt in page.tags):
                score += 2

        title_lower = page.title.lower()
        if query_lower in title_lower:
            score += 5
        else:
            for term in terms:
                if term in title_lower:
                    score += 2

        content_lower = page.content.lower()
        for term in terms:
            idx = content_lower.find(term)
            if idx != -1:
                score += 1
                if not snippet:
                    start = max(0, idx - 40)
                    end = min(len(page.content), idx + len(term) + 80)
                    raw = page.content[start:end].replace("\n", " ").strip()
                    snippet = ("..." if start > 0 else "") + raw + ("..." if end < len(page.content) else "")

        if score > 0:
            if not snippet:
                first = next((l.strip() for l in page.content.split("\n") if l.strip()), "")
                snippet = first[:117] + "..." if len(first) > 120 else first
            matches.append({
                "slug": slug, "title": page.title, "score": score,
                "snippet": snippet, "category": page.category,
                "confidence": page.confidence,
            })

    matches.sort(key=lambda m: m["score"], reverse=True)
    limited = matches[:limit]
    storage.append_log(paths, now=now, operation="query", pages=[m["slug"] for m in limited],
                       summary=f"query {text!r} -> {len(limited)} of {len(matches)}")
    return {
        "n_matches": len(matches),      # total pages that scored > 0
        "n_returned": len(limited),     # how many are in `matches` after the limit
        "matches": limited,
        "corrupt_pages": corrupt,
    }
