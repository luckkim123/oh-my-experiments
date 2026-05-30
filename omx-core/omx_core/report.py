"""omx_core.report — parse exp-analyze report.md evidence tags (Claude-free).

exp-analyze writes findings as strict, line-oriented triplets (skills/exp-analyze
/SKILL.md, sciomc evidence-tag pattern):

    [FINDING] <one-line claim>
    [EVIDENCE: <source that proves it>]
    [CONFIDENCE: HIGH|MED|LOW]

Tags are bracket-anchored, never nested, and always appear in that fixed order.
That makes a pure regex parse deterministic and unit-testable — so it lives in
the core, not the skill. exp-design (#5) and exp-loop (#6) both read findings
through this. Malformed tag runs loud-fail (OmxError) rather than silently
dropping a finding (repo silent-fallback lesson).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from omx_core.omx_paths import OmxError

_FINDING = re.compile(r"\A\[FINDING\]\s*(.*\S)\s*\Z")
_EVIDENCE = re.compile(r"\A\[EVIDENCE:\s*(.*\S)\s*\]\Z")
_CONFIDENCE = re.compile(r"\A\[CONFIDENCE:\s*(HIGH|MED|LOW)\s*\]\Z")
# any line that opens with a known tag bracket (used to detect orphan/misordered tags)
_ANY_TAG = re.compile(r"\A\[(FINDING|EVIDENCE|CONFIDENCE)\b")


class ReportParseError(OmxError):
    """A report.md evidence-tag run is malformed (orphan/misordered/incomplete)."""


@dataclass(frozen=True)
class Finding:
    """One evidence-tagged finding from a report.md."""
    claim: str
    evidence: str
    confidence: str  # "HIGH" | "MED" | "LOW"


def parse_findings(text: str) -> list[Finding]:
    """Parse all [FINDING]/[EVIDENCE]/[CONFIDENCE] triplets from report.md text.

    Non-tag lines between triplets are ignored (prose, headings, image refs).
    Raises ReportParseError if a [FINDING] is not immediately followed (skipping
    nothing) by a matching [EVIDENCE] then [CONFIDENCE], or if an orphan
    [EVIDENCE]/[CONFIDENCE] appears with no open [FINDING]. (Task 2 fills these.)
    """
    findings: list[Finding] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if _ANY_TAG.match(line) and not _FINDING.match(line):
            raise ReportParseError(
                f"orphan or malformed evidence/confidence tag with no open [FINDING] "
                f"at line {i + 1}: {line!r}")
        m = _FINDING.match(line)
        if not m:
            # plain prose / heading / image ref between findings — skip
            i += 1
            continue
        claim = m.group(1)
        ev_line = lines[i + 1].strip() if i + 1 < n else ""
        cf_line = lines[i + 2].strip() if i + 2 < n else ""
        ev = _EVIDENCE.match(ev_line)
        if not ev:
            raise ReportParseError(
                f"[FINDING] at line {i + 1} not followed by [EVIDENCE: ...] (got {ev_line!r})")
        cf = _CONFIDENCE.match(cf_line)
        if not cf:
            raise ReportParseError(
                f"[FINDING] at line {i + 1} not followed by a valid "
                f"[CONFIDENCE: HIGH|MED|LOW] (got {cf_line!r})")
        findings.append(Finding(claim=claim, evidence=ev.group(1), confidence=cf.group(1)))
        i += 3
    return findings
