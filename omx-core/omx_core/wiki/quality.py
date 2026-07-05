"""omx_core.wiki.quality — numeric page-quality score (#3, spec 3.6).

Score is ADVISORY: below-floor pages are ingested with confidence forced to
'low' and the score recorded for lint to surface — never rejected (INV-1: lint
reports, never auto-fixes; INV-2: knowledge accrues without loss).
"""
from __future__ import annotations

import re

#: Profile override slot: metrics.yaml key `wiki_quality_floor` (D12).
QUALITY_FLOOR = 50

_GENERIC_TAGS = frozenset({"auto-captured", "misc", "notes", "todo", "wip"})
_WEAK_TITLES = frozenset({"notes", "misc", "update", "todo"})
_SOURCE_MARKER = re.compile(r"(\.\w+:\d+|`[^`]+`|\[EVIDENCE)")
_DIGIT = re.compile(r"\d")


def score_page(content: str, tags: list, *, title: str = "") -> tuple[int, list]:
    score, reasons = 100, []
    body = (content or "").strip()
    if len(body) < 120:
        score -= 30; reasons.append("body-under-120-chars")
    if not _DIGIT.search(body):
        score -= 20; reasons.append("no-numeric-token")
    if not _SOURCE_MARKER.search(body):
        score -= 20; reasons.append("no-source-marker")
    tag_set = {str(t).strip().lower() for t in (tags or []) if str(t).strip()}
    if not tag_set or tag_set <= _GENERIC_TAGS:
        score -= 10; reasons.append("generic-only-tags")
    t = (title or "").strip().lower()
    if len(t.split()) < 2 or t in _WEAK_TITLES:
        score -= 10; reasons.append("weak-title")
    return max(score, 0), reasons
