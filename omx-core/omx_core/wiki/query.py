"""Read-only wiki views backed exclusively by hq's post-store query verb."""
from __future__ import annotations

from omx_core.omx_paths import OmxPaths
from omx_core.wiki.hq_backend import HqUnavailable, hq_json


def _post_store_pages(paths: OmxPaths, status: str | None) -> tuple[list[dict], dict]:
    """Shape hq posts into the catalog used by list and queue-launch.

    An unreadable post store is not an empty one: the launch gate must warn
    rather than read its old empty wiki directory as evidence of no leads.
    """
    args = ["query"]
    if status is not None:
        args += ["--status", status]
    try:
        posts = hq_json(paths.root, *args).get("posts", [])
    except HqUnavailable as exc:
        return [], {"ok": False, "count": 0, "total": 0, "error": str(exc)}
    if not isinstance(posts, list):
        return [], {"ok": False, "count": 0, "total": 0,
                    "error": "hq returned invalid posts"}
    pages = []
    for post in posts:
        fields = post.get("fields") or {}
        status_value = fields.get("status")
        if status_value in (None, "", "none"):
            continue
        pages.append({"slug": post.get("id"), "title": post.get("title"),
                      "category": fields.get("topic"), "status": status_value,
                      "blocked_on": None})
    # `total` is the DENOMINATOR and it has to survive the filter above. The
    # queue-launch gate distinguishes "no open gates" from "nobody has ever
    # filed one" -- one measured workspace had 540 pages and 0 with a blocking
    # status, so every launch that round cleared a gate that had never held
    # anything. It can only tell those apart against the count of posts that
    # EXIST, not the count that already carry a status: filtering first makes
    # the two numbers identical and the warning unreachable.
    return pages, {"ok": True, "count": len(pages), "total": len(posts),
                   "error": None}


def enumerate_pages(paths: OmxPaths, *, status: str | None = None) -> dict:
    """Catalog post heads only; legacy wiki files are deliberately no longer read."""
    pages, info = _post_store_pages(paths, status)
    return {"pages": pages, "corrupt_pages": [], "post_store": info}


#: The store's explicit-absence sentinel. hq's ranker already reads `none` this
#: way (`rank.field_text`); omx has to agree or the same field means two things.
_ABSENT = "none"


def _field(post: dict, name: str) -> str:
    value = str((post.get("fields") or {}).get(name) or "").strip()
    return "" if value.lower() == _ABSENT else value


def _snippet(post: dict) -> str:
    """First non-blank body line, else the summary -- never the word "none".

    A keyword query carries no body (hq omits it there), so this falls through
    to `summary:`, and a post whose summary is the absence sentinel used to
    render a snippet reading literally `none`.
    """
    body = str(post.get("body") or "")
    return next((line.strip() for line in body.splitlines() if line.strip()),
                _field(post, "summary"))[:120]


#: Wide enough that the field tier always outranks the body tier, matching hq's
#: lexicographic (field, body) sort. `field * 10 + body` did NOT: a post scoring
#: (7, 34.96) composed to 104 and sat BELOW one scoring (10, 0) at 100, so a
#: consumer re-sorting by the number it was handed got a different order than
#: the list it was handed -- the two-readers-of-one-number defect, this time
#: with the reader being whoever consumed the JSON.
_FIELD_TIER = 1000


def _scalar(field_score, body_score) -> int:
    """One sortable integer that agrees with hq's ordering.

    The body term is clamped to the tier width. A post would need a thousand
    keyword occurrences to reach the clamp, and losing the distinction between
    1000 and 1001 occurrences inside one field tier is a smaller lie than
    reporting a number that contradicts the order.
    """
    return int(field_score) * _FIELD_TIER + min(int(round(float(body_score))),
                                                _FIELD_TIER - 1)


def query_wiki(paths: OmxPaths, *, now: str, text: str, tags: list | None = None,
               category: str | None = None, limit: int = 20) -> dict:
    """Search hq, retaining OMX's result shape and pre-limit match count.

    Metadata weighting is explicitly opt-in in hq. ``score`` preserves the
    old scalar contract as hq's documented ``field * 10 + body`` composition.
    """
    args = ["query", "--keyword", text, "--weight-metadata"]
    if category is not None:
        args += ["--topic", category]
    result = hq_json(paths.root, *args)
    posts = result.get("posts")
    if not isinstance(posts, list):
        raise HqUnavailable("hq query returned an invalid posts list")
    wanted_tags = {tag.lower() for tag in tags or []}
    matches = []
    for post in posts:
        fields = post.get("fields") or {}
        keywords = {tag.strip().lower() for tag in str(fields.get("keywords") or "").split(",")
                    if tag.strip()}
        if wanted_tags and not wanted_tags.intersection(keywords):
            continue
        score = post.get("score") or {}
        field_score = score.get("field", 0)
        body_score = score.get("body", 0)
        try:
            combined = _scalar(field_score, body_score)
        except (TypeError, ValueError) as exc:
            raise HqUnavailable(f"hq query returned invalid score: {exc}") from exc
        matches.append({"slug": post.get("id"), "title": post.get("title"),
                        "score": combined, "snippet": _snippet(post),
                        "category": fields.get("topic"),
                        "confidence": fields.get("confidence"),
                        "status": fields.get("status")})
    limited = matches[:limit]
    return {"n_matches": len(matches), "n_returned": len(limited), "matches": limited,
            "corrupt_pages": []}
