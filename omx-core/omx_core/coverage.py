"""omx_core.coverage — report vocabulary/engine completeness lint (Claude-free).

GAP 4 from the dr-harder reporting incident. An exp-analyze report.md can cover
only a slice of the profile vocabulary (the eval-side scalars) and skip both the
training-dynamics diagnostic GROUPS and the profile's training-log diagnostic
ENGINE, and still read as "done". The teacher report referenced ~29/51 vocab
tokens yet cited ZERO engine DIAGNOSIS output — a count-only lint waves that
through. So this checks TWO things, declared by the profile (the workspace owns
the domain knowledge; the core owns the mechanism):

- every diagnostic GROUP in profile['groups'] has >=1 of its metrics referenced
  in the report (you touched each diagnostic family, not just the easy ones);
- if profile['engine_markers'] is declared, >=1 marker appears in the report
  (the analysis was grounded in the engine's output, not hand-extracted scalars).

Both profile fields are OPTIONAL: a profile with neither cannot fail (back-compat
with every pre-existing metrics.yaml). Matching is lenient leaf-token substring —
'Loss/cost_value' in the profile matches a bare 'cost_value' in prose — because
the goal is to catch a whole group/engine being skipped, not to police wording.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from omx_core.omx_paths import OmxError


@dataclass(frozen=True)
class CoverageResult:
    """Outcome of a report coverage lint."""
    ok: bool
    missing_groups: list[str] = field(default_factory=list)
    engine_cited: bool = True
    # groups that were declared and checked (for transparency in the CLI output)
    checked_groups: list[str] = field(default_factory=list)
    markers_declared: list[str] = field(default_factory=list)
    # per-group (hit, total) token counts so the caller sees WHERE coverage is thin
    group_hits: dict[str, tuple[int, int]] = field(default_factory=dict)


def _leaf(token: str) -> str:
    """The last path segment of a metric token, lowercased ('Loss/cost_value'->'cost_value')."""
    return token.split("/")[-1].strip().lower()


def _referenced(token: str, haystack_lower: str) -> bool:
    """True if the metric's leaf token (or its full token) appears in the report text."""
    leaf = _leaf(token)
    full = token.strip().lower()
    # require length > 2 so short leaves like 'kl' still match but empties don't
    candidates = {c for c in (leaf, full) if len(c) > 1}
    return any(c in haystack_lower for c in candidates)


def check_coverage(report_text: str, profile: dict) -> CoverageResult:
    """Lint a report.md's text against a profile's diagnostic groups + engine markers.

    profile['groups'] (optional): mapping {group_name: [metric, ...]} of non-empty
    lists. Each group passes if ANY of its metrics is referenced in report_text.
    profile['engine_markers'] (optional): list of marker strings (e.g. 'DIAGNOSIS',
    'changepoint'); engine_cited is True iff >=1 appears in report_text. When a field
    is absent its check is vacuously satisfied (back-compat). Loud-fails (OmxError) on
    a malformed groups field — a typo in the profile must not silently disable the lint.
    """
    text_lower = report_text.lower()

    groups = profile.get("groups")
    missing_groups: list[str] = []
    checked_groups: list[str] = []
    if groups is not None:
        if not isinstance(groups, dict):
            raise OmxError(
                f"profile['groups'] must be a mapping {{name: [metric,...]}}, "
                f"got {type(groups).__name__}")
        for name, metrics in groups.items():
            if not isinstance(metrics, list) or len(metrics) == 0:
                raise OmxError(
                    f"profile['groups'][{name!r}] must be a non-empty list of metrics")
            checked_groups.append(name)
            if not any(_referenced(m, text_lower) for m in metrics):
                missing_groups.append(name)

    markers = profile.get("engine_markers")
    markers_declared: list[str] = []
    if markers is not None:
        if not isinstance(markers, list) or len(markers) == 0:
            raise OmxError(
                "profile['engine_markers'] must be a non-empty list of marker strings")
        markers_declared = [str(m) for m in markers]
        engine_cited = any(str(m).strip().lower() in text_lower for m in markers if str(m).strip())
    else:
        engine_cited = True  # no markers declared -> engine citation not required

    ok = (not missing_groups) and engine_cited
    return CoverageResult(
        ok=ok,
        missing_groups=missing_groups,
        engine_cited=engine_cited,
        checked_groups=checked_groups,
        markers_declared=markers_declared,
    )
