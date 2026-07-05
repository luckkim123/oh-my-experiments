"""omx_core.proposal — proposal-lint + probe-novelty (spec 3.10).

Mechanizes the self-approval gap in exp-design: the discriminating-prediction
contract (H1/H2 must predict DIFFERENT outcomes) becomes a loud-fail lint, and
probe-novelty warns when the probe family was already tried. Lint = gate (rc 2);
novelty = judgment (warn only).
"""
from __future__ import annotations

import re

_H1 = re.compile(r"(?m)^\[H1-PREDICTS\]\s*(.*\S)\s*$")
_H2 = re.compile(r"(?m)^\[H2-PREDICTS\]\s*(.*\S)\s*$")
_ANALYSIS_REF = re.compile(r"[a-z][a-z0-9]*-\d{8}-\d{6}")
_HEADING = re.compile(r"(?m)^##\s+(.*)$")
_STOP = frozenset({"the", "and", "for", "with", "all", "else", "identical",
                   "predicts", "change", "within", "below", "unchanged"})


def _section(text: str, title_substr: str) -> str | None:
    """Body of the first '## ' section whose heading contains title_substr."""
    matches = list(_HEADING.finditer(text))
    for i, m in enumerate(matches):
        if title_substr.lower() in m.group(1).lower():
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            return text[m.end():end]
    return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def lint_proposal(text: str) -> dict:
    issues = []

    def add(rule, message):
        issues.append({"rule": rule, "message": message})

    probe = _section(text, "discriminating probe")
    scope = probe if probe is not None else text
    h1, h2 = _H1.search(scope), _H2.search(scope)
    if not h1 or not h2:
        add("h1h2-missing",
            "the probe section must carry [H1-PREDICTS] and [H2-PREDICTS] lines "
            "(what each top hypothesis predicts the probe outcome to be)")
    elif _norm(h1.group(1)) == _norm(h2.group(1)):
        add("h1h2-identical",
            "H1 and H2 predict the SAME outcome — the probe does not discriminate; "
            "pick a probe whose outcome separates them")

    diag = _section(text, "diagnosis")
    if diag is None:
        add("diagnosis-missing", "no '## Diagnosis' section")
    elif "[EVIDENCE:" not in diag:
        add("diagnosis-unevidenced",
            "the Diagnosis section carries no [EVIDENCE: ...] tag — every lane claim "
            "must trace to the source report/code")

    if not _ANALYSIS_REF.search(text):
        add("no-analysis-ref",
            "no analysis/proposal id token found — the proposal must cite the "
            "grounding analysis id (e.g. diagnose-YYYYMMDD-HHMMSS)")

    if not any("pending approval" in m.group(1).lower() for m in _HEADING.finditer(text)):
        add("no-pending-approval", "no '## Status: pending approval' heading (D4 gate)")

    return {"ok": not issues, "issues": issues}


def probe_tokens(text: str) -> set:
    scope = _section(text, "discriminating probe") or text
    toks = re.findall(r"[a-z][a-z0-9_]{2,}", scope.lower())
    return {t for t in toks if t not in _STOP and not t.startswith("h1") and not t.startswith("h2")}


def jaccard(a: set, b: set) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0
