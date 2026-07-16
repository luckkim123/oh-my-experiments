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
from omx_core.wiki.types import WikiError, STATUSES, BLOCKING_STATUSES
from omx_core.wiki import storage
from omx_core.wiki.quality import QUALITY_FLOOR


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

    a-1: >=2 SAME-category pages sharing a tag where EVERY sharing page is
         confidence 'high' -> they may assert conflicting high-confidence
         conclusions; flag for review. Scale re-validation (2026-07-16,
         253-page corpus): unconstrained all-high flagged 128 tags (62% of
         contradiction output) because common domain tags are shared by many
         compatible findings; group size does not discriminate (82/128 noisy
         groups were pairs); same-category cut it to 43. An all-high group
         SPANNING categories is normal cross-category co-tagging — skipped
         entirely, never demoted to a-2 (demoting keeps total volume unchanged).
    a-3: a tag spanning both 'high' and 'low' confidence -> a low page may shadow
         the authoritative conclusion; flag for review.
    a-2: a tag spanning >1 category -> classification drift; flag for review.
    One issue per tag (a-1 > a-3 > a-2 takes precedence for the same tag)."""
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
        # a-1: all sharing pages are high-confidence AND same-category (see docstring
        # for the 2026-07-16 scale re-validation). A multi-category all-high group is
        # skipped entirely — falling through to a-2 would just relabel the noise.
        if all(g.confidence == "high" for g in group):
            if len({g.category for g in group}) == 1:
                issues.append({
                    "slug": slugs[0], "severity": "info", "type": "contradiction-candidate",
                    "message": (f"{len(group)} high-confidence {group[0].category!r} pages "
                                f"share tag {tag!r}; review whether their conclusions "
                                f"conflict: {', '.join(slugs)}"),
                })
            continue
        # a-3: the group spans both 'high' and 'low' confidence -> a low page may
        # shadow the authoritative conclusion (OMC smell, keyed on tags in omx idiom).
        confs = {g.confidence for g in group}
        if "high" in confs and "low" in confs:
            issues.append({
                "slug": slugs[0], "severity": "info", "type": "contradiction-candidate",
                "message": (f"tag {tag!r} spans both high and low confidence pages; "
                            f"review whether the low page shadows or contradicts the "
                            f"high-confidence conclusion: {', '.join(slugs)}"),
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


# 0.5, not a higher bar: a real slug is truncated to 64 chars (storage.title_to_slug),
# so an evolved-title duplicate carries divergent tail-noise tokens (e.g. a clipped
# word, 'only'/'still') that inflate the union. The observed real pair
# engine_gap_eval_adapter_* shares 7 content tokens yet scores 0.583 — 0.6 missed it.
_NEAR_DUP_JACCARD = 0.5
_STOP_TOKENS = frozenset({"the", "a", "an", "and", "or", "of", "to", "is", "in", "on", "md"})


def _slug_tokens(slug: str) -> set:
    """Tokens of a slug for similarity (underscore split, stopwords + '.md' dropped).
    A title-derived slug (storage.title_to_slug) is words joined by underscores, so
    this recovers the title's content words without re-reading the page."""
    raw = slug[:-3] if slug.endswith(".md") else slug
    return {t for t in raw.split("_") if t and t not in _STOP_TOKENS}


def _near_duplicate_candidates(pages: dict) -> list:
    """Near-duplicate SIGNALS (INV-1: candidates only, never a verdict). Two pages
    whose slug tokens overlap at Jaccard >= _NEAR_DUP_JACCARD are flagged for a human
    to read both bodies. This catches the slug-fork failure mode: the SAME knowledge
    re-added under an evolved title forks the slug instead of merging (omx wiki add is
    append-merge ONLY on an identical title-derived slug). No embeddings (hard
    constraint) — pure lexical overlap. One issue per unordered pair, keyed on the
    sorted-first slug; deterministic by sorted iteration."""
    items = sorted((slug, _slug_tokens(slug)) for slug in pages)
    issues = []
    for i in range(len(items)):
        slug_a, toks_a = items[i]
        if not toks_a:
            continue
        for j in range(i + 1, len(items)):
            slug_b, toks_b = items[j]
            if not toks_b:
                continue
            union = toks_a | toks_b
            jaccard = len(toks_a & toks_b) / len(union) if union else 0.0
            if jaccard >= _NEAR_DUP_JACCARD:
                # 'other' carries the counterpart slug as DATA: gc's MERGE suggester
                # consumes the pair structurally, never by parsing the message.
                issues.append({
                    "slug": slug_a, "severity": "info", "type": "near-duplicate",
                    "other": slug_b,
                    "message": (f"slug overlaps {slug_b!r} at jaccard {jaccard:.2f}; "
                                f"read both bodies — if one topic, gc-merge them"),
                })
    return issues


def lint_wiki(paths: OmxPaths, *, now: str, stale_days: int = 30,
              max_page_size: int = 10240, quality_floor: int = QUALITY_FLOOR) -> dict:
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
        if page.quality_score is not None and page.quality_score < quality_floor:
            issues.append({"slug": slug, "severity": "info", "type": "low-quality",
                           "message": f"quality_score {page.quality_score} < {quality_floor}"})
        if page.status is not None:
            if page.status not in STATUSES:
                # a typo'd status silently exits the enumeration AND the launch gate
                # (parse never loud-fails on it) — the failure class, so flag it here.
                issues.append({"slug": slug, "severity": "info", "type": "unknown-status",
                               "message": f"status {page.status!r} not in {list(STATUSES)}"})
            elif page.status != "resolved":
                # an open actionable lead: warning if it blocks a launch, info if soft.
                sev = "warning" if page.status in BLOCKING_STATUSES else "info"
                issues.append({"slug": slug, "severity": sev, "type": "open-lead",
                               "message": f"actionable status {page.status!r}; carry it into the "
                                          f"next summary/plan or resolve it"})

    issues.extend(_contradiction_candidates(pages))
    issues.extend(_near_duplicate_candidates(pages))

    by_type = dict(Counter(i["type"] for i in issues))
    stats = {"total_pages": len(slugs), "by_type": by_type}
    return {"issues": issues, "stats": stats}
