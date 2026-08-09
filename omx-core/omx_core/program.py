"""omx_core.program — program-lint + the PLAN/HANDOFF skeletons.

Mechanizes the escalation gap in the program layer. `proposal-lint` guards the
single-probe artifact; nothing guarded `programs/<id>/PLAN.md`, the document
that commits days of GPU. The 2026-08 `dgx-final-scaleup` incident is the
reference case: the plan's own coupling section named a knob under a tier
literally titled "a decision is required", resolved it internally against
*measurement readability*, and never listed it in the section titled
"decisions this program cannot make". The run then spent 11x the compute of
its reference to land 2% away from it.

Two rules follow, and they are the whole point of this module:

  * the requester's objective is carried VERBATIM, so every held-or-changed
    knob can be argued against it rather than against a substituted one; and
  * anything the plan marks `[DECISION-REQUIRED: <slug>]` must surface in the
    user-decision section — a plan may not both declare a decision necessary
    and take it.

Lint = gate (rc 2), same contract as proposal-lint.
"""
from __future__ import annotations

import re

# Shared markdown-section helper; the two lint modules agree on what '## ' means.
from omx_core.proposal import _section as _md_section

_MARKER = re.compile(r"\[DECISION-REQUIRED:\s*([^\]]+?)\s*\]")
_ANY_HEADING = re.compile(r"(?m)^(#{2,})\s+(.*)$")

# The phrase family that means "this is not settled". Korean forms are kept
# alongside the English: these repos treat Korean trigger words as functional
# data, and the plan that failed was authored bilingually.
_DECISION_PHRASE = re.compile(
    r"(a\s+)?decisions?\s+(is|are)\s+(required|needed)"
    r"|requires?\s+a\s+decision"
    r"|decision\s+required"
    r"|결정이\s*필요"
    r"|판단이\s*필요",
    re.IGNORECASE)

OBJECTIVE_HEADING = "Objective"
DECISIONS_HEADING = "Decisions for the user"
PREDICTED_HEADING = "Predicted outcome"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.strip().lower()).strip("-")


def _section_any(text: str, title_substr: str) -> str | None:
    """Body of the first heading at ANY depth (## or deeper) matching title_substr.

    `_md_section` only sees '## '; the coupling tiers are '### ', so they need this.
    """
    ms = list(_ANY_HEADING.finditer(text))
    for i, m in enumerate(ms):
        if title_substr.lower() in m.group(2).lower():
            end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
            return text[m.end():end]
    return None


def _substantive(body: str) -> bool:
    """True when a section carries content beyond blanks and table rules."""
    for line in body.splitlines():
        s = line.strip()
        if s and not set(s) <= set("|-: "):
            return True
    return False


def lint_program(text: str) -> dict:
    """Gate a programs/<id>/PLAN.md. Returns {"ok": bool, "issues": [...]}"""
    issues = []

    def add(rule, message):
        issues.append({"rule": rule, "message": message})

    objective = _md_section(text, OBJECTIVE_HEADING)
    if objective is None:
        add("objective-missing",
            f"no '## {OBJECTIVE_HEADING}' section — the plan must open with the "
            "requester's stated goal so every knob decision argues against it")
    elif not re.search(r"(?m)^\s*>", objective):
        add("objective-not-verbatim",
            f"the '## {OBJECTIVE_HEADING}' section carries no '>' blockquote — quote the "
            "requester's own words, do not paraphrase (a paraphrased objective drifts, "
            "and a drifted objective makes every downstream trade look correct)")

    decisions = _md_section(text, DECISIONS_HEADING)
    if decisions is None:
        add("decisions-section-missing",
            f"no '## {DECISIONS_HEADING}' section — a plan with no place to escalate will "
            "resolve the user's decisions itself. If the plan already has one under another "
            f"name ('Open questions', 'Decisions this program cannot make'), rename it to "
            f"'## {DECISIONS_HEADING}': the marker cross-check needs one canonical heading, "
            "and heading drift is how the link to the coupling section gets lost")

    marked = {_slug(m.group(1)) for m in _MARKER.finditer(text)}
    listed = {_slug(m.group(1)) for m in _MARKER.finditer(decisions or "")}
    orphans = sorted(marked - listed)
    if orphans:
        add("decision-not-escalated",
            f"marked [DECISION-REQUIRED] but absent from '## {DECISIONS_HEADING}': "
            f"{orphans} — a plan may not both declare a decision necessary and take it")

    # A populated tier 2 with no markers at all is the same failure wearing a
    # different face: the coupling was found, and then nobody had to escalate it.
    tier2 = _section_any(text, "tier 2")
    if tier2 is not None and _substantive(tier2) and not _MARKER.search(tier2):
        add("tier2-unmarked",
            "the tier-2 coupling section has content but no [DECISION-REQUIRED: <slug>] "
            "marker — a coupling real enough to list is real enough to escalate; mark each "
            "row, or move it to tier 1/3 if it is genuinely settled")

    # The incident signature in prose: a line asserting that a decision is required,
    # outside the decision list, carrying no marker. Headings are section labels
    # rather than claims about a specific knob, so they are exempt.
    in_decisions = False
    for line in text.splitlines():
        h = _ANY_HEADING.match(line)
        if h:
            in_decisions = DECISIONS_HEADING.lower() in h.group(2).lower()
            continue
        if in_decisions or not _DECISION_PHRASE.search(line) or _MARKER.search(line):
            continue
        add("decision-phrase-unmarked",
            "a line outside the decision list states that a decision is required but "
            f"carries no [DECISION-REQUIRED: <slug>] marker: {line.strip()[:120]!r} — "
            "mark it and list it, or reword if it is already settled")
        break

    if _md_section(text, PREDICTED_HEADING) is None:
        add("predicted-outcome-missing",
            f"no '## {PREDICTED_HEADING}' section — state what this line is expected to "
            "produce before it is approved; a predicted null is worth knowing while it is "
            "still cheap")

    return {"ok": not issues, "issues": issues}


PLAN_TEMPLATE = """# Program: {program_id}

**Status: PENDING USER APPROVAL — this document authorizes NO launch.**

## Objective

Quote the requester's stated goal verbatim. Every decision below argues against
THIS line, not against a restatement of it.

> (paste the requester's own words here)

Redefining the objective later in this document is a re-ask, not an edit: say so
at the point of redefinition and put it in the decision list.

## Diagnosis

What the record already establishes, with `[EVIDENCE: ...]` per claim. Read the
analysis reports and `omx wiki query` first — a plan that rediscovers a settled
fact will also re-make a settled mistake.

## Parameter coupling

Three tiers. Anything in tier 2 needs a `[DECISION-REQUIRED: <slug>]` marker AND
a matching entry in the decision list below.

### Tier 1 — follows mechanically; nothing to set

### Tier 2 — real coupling; a decision is required

| knob | current | options | coupling | marker |
|:--|:--|:--|:--|:--|
| (knob) | (value) | (a) / (b) | (what it couples to) | `[DECISION-REQUIRED: <slug>]` |

### Tier 3 — no coupling to the variables under test; leave byte-identical

## Decisions for the user

One entry per tier-2 item, each repeating its `[DECISION-REQUIRED: <slug>]`
marker. Holding a knob to keep a comparison readable is a trade against the
objective, so it belongs here too.

- `[DECISION-REQUIRED: <slug>]` **question** — options / recommendation /
  why / what the other choice costs.

## Predicted outcome

What this line is expected to produce. If the honest prediction is "equivalent
to what we have", write that and let the requester decide whether to spend the
budget anyway.

## Eval schedule

Dense enough to resolve the curve. A schedule too sparse to see a transient will
report it as a plateau and fire the stop rule on an artifact.

## Wall-clock and budget

## Deferred

Enumerate `omx wiki list --status needs-experiment` and
`--status needs-apply-before-retrain`; every open lead is carried or explicitly
deferred with a reason. Silent omission is a defect.
"""


HANDOFF_TEMPLATE = """# Handoff — {program_id}

Paste as-is into the executing session. Self-contained: everything needed is
here or produced by the commands below.

## Objective (carried from PLAN.md, verbatim)

> (the same quote as PLAN.md — the executing session must be able to tell what
> the run is FOR without opening the plan)

## Hard rules

1. Launch EXACTLY ONE run, the one specified below. Anything beyond the
   pre-approved steps needs new human approval.
2. If a knob looks wrong, that is a STOP-and-report, not a judgment call.

## Held decisions

Never compress a decision into a prohibition. "X stays 250" tells the receiving
session nothing it can re-examine; the row below does.

| knob | held at | alternative considered | why held | what it costs |
|:--|:--|:--|:--|:--|
| (knob) | (value) | (the option not taken) | (reason) | (the predicted price of holding) |

## Predicted outcome

Restate the plan's prediction. If it is a null, say so here — a predicted null
that reaches the executing session unspoken becomes days of wasted machine time.

## Steps

## Reporting

All numbers are screening measurements unless the plan says otherwise. Report
measurements, never adoption conclusions.
"""
