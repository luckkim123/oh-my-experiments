---
name: exp-design
description: Design the next experiment from an exp-analyze report. Use after analyzing runs, when you need to decide what to change next — runs a 3-lane differential diagnosis (code-path / config-DR-hyperparam / measurement-artifact) over the evidence-tagged findings and proposes the single discriminating probe (the next-experiment config) as a pending-approval artifact. Reads report.md, writes proposals/<id>.md. Never launches training or eval. Triggers on "design the next experiment", "what should I change next", "diagnose why this regressed and propose a fix experiment", "다음 실험 설계", "다음에 뭘 바꿔야 할까".
argument-hint: "[--root <dir>] <path to an exp-analyze report.md, or run id + analysis id>"
---

# exp-design — 3-lane differential diagnosis → discriminating probe (next experiment)

## Overview

`exp-design` turns an exp-analyze `report.md` into the NEXT experiment. It runs a
differential diagnosis across three competing hypothesis lanes (design §1, OMC
trace pattern), picks the single **discriminating probe** — the cheapest change
whose outcome the top two hypotheses predict differently — and writes that probe
as a `pending approval` proposal in the permanent `proposals/` tree.

It NEVER launches training or eval (design D4/B8). The proposal is an artifact a
human reads and approves; exp-design's job ends at writing it.

**Announce at start:** "Using exp-design to diagnose the findings and propose the next experiment."

## Preconditions (check, don't assume)

1. A profile exists and is approved. Read `<root>/.omx/profile/metrics.yaml`. Missing
   → tell the user to run exp-init first; STOP. `pending_approval: true` still set
   → tell the user to approve it first; STOP. (Honors the exp-init hard gate.)
2. An exp-analyze `report.md` exists. The user gives either a direct path to a
   `report.md`, or a `<run_id>` + `<analysis_id>` from which you resolve it with
   `omx_paths.report_md(output_root, run_id, analysis_id)` (output_root from the
   profile's metrics.yaml). If the report is missing, say so and STOP — never
   invent findings.

## Step 1 — read the structured findings (via the core, never re-parse by hand)

Get the findings as JSON from the Claude-free parser; do NOT eyeball the markdown
for `[FINDING]` lines yourself (the parser is the contract, and it loud-fails on a
malformed report — which is a signal the report is broken, not something to paper over):

```bash
omx report-parse --path "<output_root>/<run_id>/analysis/<analysis_id>/report.md"
```

This prints `{"n_findings": N, "findings": [{"claim","evidence","confidence"}, ...]}`.
If it exits non-zero, the report is malformed — report that to the user and STOP;
do not hand-parse around it.

Also read the report.md prose yourself (with the Read tool) for the narrative
context the tags don't carry (what was compared, the baseline, the user's
question). The tags give you the structured claims; the prose gives you intent.
