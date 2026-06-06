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
    A [FINDING] claim may wrap across several prose lines (normal readable
    report writing); the parser looks ahead to the next [EVIDENCE:] within the
    block and joins the wrapped lines into one claim. Reaching another known tag
    ([CONFIDENCE]/[FINDING]/a malformed [EVIDENCE]) or the end of the text
    before any [EVIDENCE:] is a genuinely malformed block.
    Raises ReportParseError if a [FINDING] has no following [EVIDENCE], if its
    [EVIDENCE] is not followed by a valid [CONFIDENCE], or if an orphan or
    malformed [EVIDENCE]/[CONFIDENCE] appears with no open [FINDING].
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
        finding_line = i + 1  # 1-based line of the [FINDING], for error messages
        claim_parts = [m.group(1)]
        # Look ahead to the [EVIDENCE:] for this finding, joining wrapped claim
        # lines. Any other known tag (or running off the end) before [EVIDENCE]
        # means the block is malformed.
        j = i + 1
        ev = None
        while j < n:
            cand = lines[j].strip()
            if not cand:
                j += 1
                continue
            ev = _EVIDENCE.match(cand)
            if ev:
                break
            if _ANY_TAG.match(cand):
                # hit [FINDING]/[CONFIDENCE]/malformed [EVIDENCE] before evidence
                raise ReportParseError(
                    f"[FINDING] at line {finding_line} not followed by [EVIDENCE: ...] "
                    f"(got {cand!r})")
            # ordinary prose line: part of the wrapped claim
            claim_parts.append(cand)
            j += 1
        if ev is None:
            raise ReportParseError(
                f"[FINDING] at line {finding_line} not followed by [EVIDENCE: ...] "
                f"(reached end of report)")
        # j now indexes the [EVIDENCE:] line; [CONFIDENCE] must be the next
        # non-empty line after it.
        k = j + 1
        while k < n and not lines[k].strip():
            k += 1
        cf_line = lines[k].strip() if k < n else ""
        cf = _CONFIDENCE.match(cf_line)
        if not cf:
            raise ReportParseError(
                f"[FINDING] at line {finding_line} not followed by a valid "
                f"[CONFIDENCE: HIGH|MED|LOW] (got {cf_line!r})")
        claim = " ".join(claim_parts)
        findings.append(Finding(claim=claim, evidence=ev.group(1), confidence=cf.group(1)))
        i = k + 1
    return findings
