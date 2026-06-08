"""omx_core.coverage — report vocabulary/engine completeness lint (Claude-free).

GAP 4 from the dr-harder reporting incident. An exp-analyze report.md can cover
only a slice of the profile vocabulary (the eval-side scalars) and skip both the
training-dynamics diagnostic GROUPS and the profile's training-log diagnostic
ENGINE, and still read as "done". The teacher report referenced ~29/51 vocab
tokens yet cited ZERO engine DIAGNOSIS output — a count-only lint waves that
through. So this checks TWO things, declared by the profile (the workspace owns
the domain knowledge; the core owns the mechanism):

- every diagnostic GROUP in profile['groups'] is covered: by default >=1 of its
  metrics is referenced (you touched each diagnostic family, not just the easy
  ones); under opt-in strict mode (min_coverage) a FRACTION of each group's tokens
  must appear, catching a group named only once when it has several metrics;
- if profile['engine_markers'] is declared, >=1 marker appears in the report
  (the analysis was grounded in the engine's output, not hand-extracted scalars).

Both profile fields are OPTIONAL: a profile with neither cannot fail (back-compat
with every pre-existing metrics.yaml). Matching is lenient leaf-token substring —
'Loss/cost_value' in the profile matches a bare 'cost_value' in prose — because
the goal is to catch a whole group/engine being skipped, not to police wording.
"""
from __future__ import annotations

import math
import re
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
    # GAP E: groups that pass the coverage threshold (ok stays True in lenient mode)
    # but have hits < total — field-level omissions within a passing group.
    # Surfaced as a warning so the analyst cannot silently skip sub-group fields.
    partial_groups: list[str] = field(default_factory=list)
    # dr_harder 2026-06-08 incident: required SECTIONS (markdown headings, NOT metric
    # tokens) that the report must contain as headings. A whole '## generalization'
    # section was dropped and the token-group lint could not see it (OOD maps to no
    # group). Declared sections absent as headings -> hard fail. Empty when the
    # profile declares none (back-compat).
    missing_sections: list[str] = field(default_factory=list)
    # dr_harder 2026-06-08 incident: a RE-analysis shrank 25-39% in words and 40-91%
    # in data-table rows vs the report it replaced, and the lint still passed. When a
    # baseline_text is provided, compare word / [FINDING] / data-table-row counts; a
    # drop past tolerance is a regression and a hard fail. None when no baseline given.
    regression: dict | None = None


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


# markdown heading line: one or more '#' then text. We match a section token against
# the heading TEXT only (not body prose), so a passing mention buried in a paragraph
# does not satisfy a required section (the generalization-section-dropped incident).
_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+(.*)$")


def _heading_texts(report_text: str) -> list[str]:
    """Lowercased text of every markdown heading line in the report."""
    return [m.group(1).strip().lower() for m in _HEADING_RE.finditer(report_text)]


def _section_present(token: str, headings_lower: list[str]) -> bool:
    """True if the section token appears inside ANY heading's text (substring)."""
    t = token.strip().lower()
    return len(t) > 0 and any(t in h for h in headings_lower)


# a data row = a line that is a markdown table data/separator row (starts with '|').
# This is the depth signal the dr_harder rewrite gutted (per-axis x DR-level tables,
# the 10-row per-constraint table, the z-sweep ranking) while keeping the headings.
_TABLE_ROW_RE = re.compile(r"(?m)^\s*\|.*\|\s*$")
_FINDING_RE = re.compile(r"\[FINDING\]")
_WORD_RE = re.compile(r"\S+")


def _depth_counts(text: str) -> dict[str, int]:
    """Word / [FINDING] / markdown-table-row counts — the three depth signals."""
    return {
        "words": len(_WORD_RE.findall(text)),
        "findings": len(_FINDING_RE.findall(text)),
        "tables": len(_TABLE_ROW_RE.findall(text)),
    }


def _check_regression(new_text: str, baseline_text: str,
                      word_tol: float = 0.10) -> dict:
    """Compare a re-analysis against the report it replaces (dr_harder incident).

    A re-analysis must not be SHALLOWER than its predecessor. Three signals:
    - words: raw length; a soft signal (tighter prose is fine) -> word_tol slack
      (default 10%: words may drop up to 10% before counting as a regression).
    - findings: [FINDING] count = analysis units; ANY drop is a regression (dropping
      a finding means an analysis was removed, even if words were padded back).
    - tables: markdown data-row count = the per-axis/per-constraint/z-sweep tables;
      ANY drop is a regression (this is what actually got gutted, 40-91%).

    is_regression is True if findings dropped, OR tables dropped, OR words dropped past
    word_tol. Returns the per-signal old/new counts so the caller can report WHERE.
    """
    old = _depth_counts(baseline_text)
    new = _depth_counts(new_text)
    words_regressed = new["words"] < old["words"] * (1.0 - word_tol)
    findings_regressed = new["findings"] < old["findings"]
    tables_regressed = new["tables"] < old["tables"]
    is_regression = words_regressed or findings_regressed or tables_regressed
    return {
        "is_regression": is_regression,
        "words": {"old": old["words"], "new": new["words"], "regressed": words_regressed},
        "findings": {"old": old["findings"], "new": new["findings"],
                     "regressed": findings_regressed},
        "tables": {"old": old["tables"], "new": new["tables"], "regressed": tables_regressed},
        "word_tol": word_tol,
    }


def check_coverage(report_text: str, profile: dict,
                   min_coverage: float | None = None,
                   baseline_text: str | None = None) -> CoverageResult:
    """Lint a report.md's text against a profile's diagnostic groups + engine markers.

    profile['groups'] (optional): mapping {group_name: [metric, ...]} of non-empty
    lists. profile['engine_markers'] (optional): list of marker strings (e.g.
    'DIAGNOSIS', 'changepoint'); engine_cited is True iff >=1 appears in report_text.
    When a field is absent its check is vacuously satisfied (back-compat). Loud-fails
    (OmxError) on a malformed groups field — a typo in the profile must not silently
    disable the lint.

    min_coverage (optional, opt-in strict mode): None (default) keeps the lenient
    back-compat rule — a group passes if ANY of its metrics is referenced (>=1 token),
    so pre-existing workspaces are unaffected. A float in (0, 1] turns on strict mode:
    a group passes only if at least ``max(1, ceil(total * min_coverage))`` of its
    tokens are referenced, catching shallow partial coverage (a group with several
    tokens but only one named). A value outside (0, 1] loud-fails (OmxError).
    group_hits always reports per-group (hit, total) so the caller sees WHERE it is thin.

    profile['required_sections'] (optional, dr_harder 2026-06-08 incident): list of
    section tokens that MUST appear as markdown HEADINGS (not just prose). The token
    is matched against heading TEXT only, so the OOD/generalization section being
    deleted is caught even though it maps to no metric group. A declared section
    absent as a heading -> missing_sections + hard fail. Must be a list of strings.

    baseline_text (optional, dr_harder 2026-06-08 incident): the prior report this
    one replaces. When given, the report is compared on word / [FINDING] / table-row
    counts; a regression (fewer findings, fewer tables, or words down past tolerance)
    is a hard fail, so a re-analysis can never silently shrink past its predecessor.
    None -> regression gate inert (back-compat).
    """
    if min_coverage is not None and not (0.0 < min_coverage <= 1.0):
        raise OmxError(f"min_coverage must be in (0, 1], got {min_coverage!r}")

    text_lower = report_text.lower()

    groups = profile.get("groups")
    missing_groups: list[str] = []
    checked_groups: list[str] = []
    group_hits: dict[str, tuple[int, int]] = {}
    partial_groups: list[str] = []
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
            total = len(metrics)
            hits = sum(1 for m in metrics if _referenced(m, text_lower))
            group_hits[name] = (hits, total)
            # required hits: lenient (>=1) by default, ceil(total*frac) in strict mode.
            # max(1, ...) so even a tiny frac never lets a group pass with zero hits.
            required = 1 if min_coverage is None else max(1, math.ceil(total * min_coverage))
            if hits < required:
                missing_groups.append(name)
            elif hits < total:
                # GAP E: group passes threshold but has unreferenced tokens — surface
                # as partial so the analyst sees field-level omissions even when ok.
                partial_groups.append(name)

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

    # required_sections (dr_harder incident): declared sections must appear as headings
    required_sections = profile.get("required_sections")
    missing_sections: list[str] = []
    if required_sections is not None:
        if not isinstance(required_sections, list) or not all(
                isinstance(s, str) for s in required_sections):
            raise OmxError(
                "profile['required_sections'] must be a list of section-token strings")
        headings_lower = _heading_texts(report_text)
        missing_sections = [
            s for s in required_sections if not _section_present(s, headings_lower)]

    # baseline regression gate (dr_harder incident): a re-analysis must not shrink
    regression = (
        _check_regression(report_text, baseline_text)
        if baseline_text is not None else None)

    ok = (
        (not missing_groups)
        and engine_cited
        and (not missing_sections)
        and not (regression is not None and regression["is_regression"]))
    return CoverageResult(
        ok=ok,
        missing_groups=missing_groups,
        engine_cited=engine_cited,
        checked_groups=checked_groups,
        markers_declared=markers_declared,
        missing_sections=missing_sections,
        regression=regression,
        group_hits=group_hits,
        partial_groups=partial_groups,
    )
