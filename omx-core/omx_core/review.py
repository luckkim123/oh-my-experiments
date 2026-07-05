"""omx_core.review — deterministic report-review checklist (spec 3.4, mechanical layer).

Author != reviewer: this runs OUTSIDE the writing session, and the judgment
layer (agents/report-reviewer.md) runs this verb first, then judges what code
cannot (prose quality, whether evidence supports the claim). Verdict `revise`
iff any MAJOR issue. R1 records reviews; it does not gate consumption.
"""
from __future__ import annotations

import re

from omx_core.coverage import _check_regression
from omx_core.report import ReportParseError, parse_findings

_DIGIT = re.compile(r"\d")
_CODE_EXEC = re.compile(r"(\.py\b|\.json\b|\bomx |\bpython\b|\.\w+:\d+)")
_PNG = re.compile(r"\.png\b", re.IGNORECASE)
_EXEMPT_HEADINGS = ("tl;dr", "verdict", "bottom line", "next", "how to", "appendix")
_WALL_WORDS = 120
_WALL_CAP = 5


def _sections(text: str) -> list[tuple[str, str]]:
    """Split on '## ' headings -> [(heading_text, body)]. Preamble is ('', body)."""
    parts = re.split(r"(?m)^##\s+(.*)$", text)
    out = [("", parts[0])]
    for i in range(1, len(parts), 2):
        out.append((parts[i].strip(), parts[i + 1] if i + 1 < len(parts) else ""))
    return out


def review_report(text: str, *, baseline_text: str | None = None) -> dict:
    findings = []

    def add(section, issue, severity, detail=""):
        findings.append({"section": section, "issue": issue,
                         "severity": severity, "detail": detail})

    try:
        parsed = parse_findings(text)
        if not parsed:
            add("", "no-findings", "major", "no [FINDING] evidence triplets in the report")
    except ReportParseError as e:
        parsed = []
        add("", "no-findings", "major", f"findings grammar broken: {e}")

    for f in parsed:  # 26: HIGH numeric claims must cite code-exec, not a plot
        if (f.confidence == "HIGH" and _DIGIT.search(f.claim)
                and _PNG.search(f.evidence) and not _CODE_EXEC.search(f.evidence)):
            add("", "high-conf-plot-only", "major",
                f"HIGH-confidence numeric claim cites only a plot: {f.claim[:80]}")

    walls = 0
    for para in re.split(r"\n\s*\n", text):
        words = para.split()
        if len(words) > _WALL_WORDS and not _DIGIT.search(para) and walls < _WALL_CAP:
            walls += 1
            add("", "wall-of-text", "minor",
                f"{len(words)}-word paragraph with no numeric token: {para[:60]}...")

    for heading, body in _sections(text)[1:]:
        h = heading.lower()
        if any(x in h for x in _EXEMPT_HEADINGS):
            continue
        if not _DIGIT.search(body) and "[FINDING]" not in body:
            add(heading, "empty-shell-section", "minor",
                "section carries no numeric token and no finding")

    if baseline_text is not None:
        reg = _check_regression(text, baseline_text)
        if reg["is_regression"]:
            dropped = [k for k in ("words", "findings", "tables") if reg[k]["regressed"]]
            add("", "depth-regression", "major",
                f"shallower than baseline in: {', '.join(dropped)}")

    verdict = "revise" if any(f["severity"] == "major" for f in findings) else "approve"
    return {"verdict": verdict, "findings": findings}
