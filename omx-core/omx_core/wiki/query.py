"""omx_core.wiki.query — keyword + tag search (NO vector embeddings — hard constraint).

tokenize handles Latin/digits plus CJK bi-grams (so Korean research notes are
searchable — INV-2). Scoring: tag match > title match > content match (OMC
weights). A page with broken frontmatter is SKIPPED but reported in
`corrupt_pages` (W8: visible-skip, never silent, never whole-fail).
"""
from __future__ import annotations

import json
import re
import subprocess

from omx_core.omx_paths import OmxPaths
from omx_core.wiki import storage
from omx_core.wiki.types import WikiError

_LATIN = re.compile(r"[a-z0-9À-ɏ]+")
_CJK = re.compile(r"[぀-ゟ゠-ヿ一-鿿가-힯]+")

# Ranking weights (v0.7.1): keyword score is DOMINANT, not strictly primary.
# Individual weights are in [0.70, 1.00]; the worst-case combined discount is
# low 0.80 * resolved 0.70 = 0.56, so metadata intentionally re-orders NEAR-tied
# scores (the stub-sinking) while a clearly-stronger keyword match still wins.
# These are the tuning knob; adjust here, not inline. absent (None) = neutral.
_CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.92, "low": 0.80, None: 0.90}
_STATUS_WEIGHT = {
    "needs-experiment": 1.0,
    "needs-apply-before-retrain": 1.0,
    "resolved": 0.70,
    None: 1.0,
}


def _rank_weight(match: dict) -> float:
    """Weighted rank key: keyword score modified by confidence + status.
    Unknown/absent metadata -> neutral (never penalize a hand-edited value)."""
    conf = _CONFIDENCE_WEIGHT.get(match["confidence"], 0.90)
    stat = _STATUS_WEIGHT.get(match["status"], 1.0)
    return match["score"] * conf * stat


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


#: How long `hq` gets to answer. It reads one directory tree of markdown; a
#: slower answer than this means something is wrong, and a hung gate is worse
#: than a loud one.
_HQ_TIMEOUT_S = 10


def _post_store_pages(paths: OmxPaths, status: str | None) -> tuple:
    """Open leads from the `.hq/` post store, shaped like wiki pages.

    The wiki→posts conversion (vault 55a12dc8, 2026-08-28) emptied
    `community/wiki/` and moved every open lead into `community/posts/`, keeping
    the same `status:` vocabulary — store-spec §4 says `needs-apply-before-retrain`
    keeps its launch-blocking meaning there. The readers did not follow, so this
    function is the half that did: measured 2026-08-29 on the vault,
    `omx wiki list` returned 0 pages while 5 open leads (2 of them blocking) sat
    in posts, and the queue-launch gate read that zero as a pass.

    Shelling out to `hq` rather than parsing posts here is deliberate: a second
    frontmatter parser for the same format is the drift the store unification
    exists to prevent. The cost is that `hq` (shipped by `oh-my-orchestrator`)
    must be on PATH.

    Returns (pages, info). `info["ok"]` is False when the store could not be
    read — which is NOT the same as empty, and every caller must say so rather
    than treat the zero as an answer.
    """
    cmd = ["hq", "--anchor", str(paths.root), "--json", "query"]
    if status is not None:
        cmd += ["--status", status]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=_HQ_TIMEOUT_S)
        if proc.returncode != 0:
            raise RuntimeError(
                f"hq exited {proc.returncode}: {(proc.stderr or '').strip()[:200]}")
        posts = json.loads(proc.stdout).get("posts", [])
        if not isinstance(posts, list):
            raise RuntimeError("unexpected `hq query` output shape")
    except FileNotFoundError:
        return [], {"ok": False, "count": 0,
                    "error": "hq not on PATH (ships with oh-my-orchestrator)"}
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return [], {"ok": False, "count": 0,
                    "error": f"{type(exc).__name__}: {exc}"}

    pages = []
    for p in posts:
        fields = p.get("fields") or {}
        st = fields.get("status")
        if st in (None, "", "none"):
            continue          # a post with no status is not a backlog item
        pages.append({
            "slug": p.get("id"), "title": p.get("title"),
            "category": fields.get("topic"), "status": st,
            "blocked_on": None,     # posts carry no blocked_on field
        })
    return pages, {"ok": True, "count": len(pages), "error": None}


def enumerate_pages(paths: OmxPaths, *, status: str | None = None) -> dict:
    """Deterministic (no-scoring) catalog, optionally filtered to one status value.

    Returns {pages:[{slug, title, category, status, blocked_on}], corrupt_pages:[...],
    post_store:{ok, count, error}}. This is the "backlog by construction" surface —
    ZERO keyword involvement — and it backs BOTH `omx wiki list` and the queue-launch
    gate, so the human's view and the gate's view can never drift. Read-only; no lock;
    a corrupt page is visible-skipped.

    Two sources, unioned: the wiki dir (legacy, empty on a converted store) and the
    `.hq/` post store, which is where open leads live now — see `_post_store_pages`.
    Slugs cannot collide: a post id always contains '/'."""
    pages = []
    corrupt = []
    for slug in storage.list_pages(paths):
        try:
            page = storage.read_page(paths, slug)
        except WikiError:
            corrupt.append(slug)
            continue
        if page is None:
            continue
        if status is not None and page.status != status:
            continue
        pages.append({
            "slug": slug, "title": page.title, "category": page.category,
            "status": page.status, "blocked_on": page.blocked_on,
        })
    post_pages, post_info = _post_store_pages(paths, status)
    pages.extend(post_pages)
    return {"pages": pages, "corrupt_pages": corrupt, "post_store": post_info}


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

        page_tags_lower = {pt.lower() for pt in page.tags}
        if tags:
            overlap = [t for t in tags if t.lower() in page_tags_lower]
            score += len(overlap) * 3
        for term in terms:
            if any(term in pt for pt in page_tags_lower):
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
                first = next((ln.strip() for ln in page.content.split("\n") if ln.strip()), "")
                snippet = first[:117] + "..." if len(first) > 120 else first
            matches.append({
                "slug": slug, "title": page.title, "score": score,
                "snippet": snippet, "category": page.category,
                "confidence": page.confidence, "status": page.status,
            })

    matches.sort(key=lambda m: (_rank_weight(m), m["score"]), reverse=True)
    limited = matches[:limit]
    storage.append_log(paths, now=now, operation="query", pages=[m["slug"] for m in limited],
                       summary=f"query {text!r} -> {len(limited)} of {len(matches)}")
    return {
        "n_matches": len(matches),      # total pages that scored > 0
        "n_returned": len(limited),     # how many are in `matches` after the limit
        "matches": limited,
        "corrupt_pages": corrupt,
    }
