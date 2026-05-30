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

## Step 2 — 3-lane differential diagnosis (the core IP, design §1 / OMC trace pattern)

You have the structured findings + the report prose. Now diagnose WHY the result
is what it is, by competing hypotheses across three lanes. This mirrors OMC's
trace skill (3 lanes; evidence for/against; critical unknown; discriminating
probe). Apply the repo's own discipline: differential diagnosis first (a cause
that hits one channel but not another is the strongest clue), never a generic
"schedule/curriculum/adaptive" guess without evidence.

For EACH of the three lanes, write a short block:

1. **Code-path / implementation lane.** Hypothesis: the result is caused by the
   model/algorithm/reward/constraint code itself (a function does not do what its
   name says; a path is only exercised by some axes). Evidence FOR / AGAINST drawn
   from the findings + prose. Critical unknown. Candidate probe.
2. **Config / DR / hyperparameter lane.** Hypothesis: the result is caused by a
   config value — DR range/curriculum, a hyperparameter, an env setting, ocean
   current, a seed. Evidence FOR / AGAINST. Critical unknown. Candidate probe.
3. **Measurement / artifact lane.** Hypothesis: the result is not a real
   regression at all — it is an eval/measurement artifact (sample-env divergence
   vs heavy-tail confusion; wrong eval mode; output-naming/path mix-up; aggregation
   that hides per-env variance). Evidence FOR / AGAINST. Critical unknown.
   Candidate probe.

Rules while diagnosing:
- Rank evidence by strength (strongest → weakest): controlled reproduction / a
  uniquely discriminating artifact > a primary artifact with tight provenance
  (an exact metric from summary.json, a code file:line) > multiple independent
  sources agreeing > single-source inference > weak circumstantial (naming,
  timing) > speculation. A `[CONFIDENCE: HIGH]` finding with a code-exec number
  outranks a `[CONFIDENCE: MED]` inference.
- A finding's `confidence` tag is an input, not the verdict: a HIGH-confidence
  measurement can still SUPPORT the measurement-artifact lane (it proves a number,
  not its cause).
- Do NOT pre-commit to a lane. The point is to let evidence separate them. If two
  lanes fit equally, that IS the finding — and the probe must be the test that
  splits them.

## Step 3 — pick the single discriminating probe (= the next experiment)

From the three lanes, identify the leading hypothesis and the strongest remaining
alternative. The **discriminating probe** is the cheapest next experiment whose
outcome those two predict DIFFERENTLY (OMC trace: "the highest-value next step to
collapse uncertainty", "the cheapest probe that would discriminate it from the
next-best alternative"). State, explicitly:

- **What each top hypothesis predicts** the probe's outcome would be (they must
  differ — if they predict the same thing, the probe does not discriminate; pick
  another).
- **The exact change** the probe makes: which single config value / code path /
  measurement method changes, and to what. Honor the repo "minimum-change" rule:
  change ONE variable so the next run is not confounded.
- **What result confirms which hypothesis.**

The discriminating probe, expressed as a concrete change to the training/eval
setup, IS the proposed next experiment. It is a PROPOSAL — never run it.

## Step 4 — write the proposal (permanent tree, via the core — never hand-write paths)

1. Choose a `proposal_id` = `<YYYYMMDD-HHMMSS>-next` (the verb is literally `next`,
   matching design §10.1). Get the timestamp from `date +%Y%m%d-%H%M%S` via Bash.
2. Resolve `output_root` from the profile's `metrics.yaml` (the same value
   exp-analyze used) and the `run_id` (the run the analysis was about).
3. Draft the proposal markdown. It MUST contain, in order:
   - **`# Next-experiment proposal — pending approval`** heading, with the
     `run_id`, source `analysis_id`, and the `proposal_id`.
   - **`## Diagnosis`** — the three lane blocks (code-path / config-DR-hyperparam /
     measurement-artifact), each with evidence FOR/AGAINST and its critical unknown,
     ending with the ranked leading hypothesis vs strongest alternative.
   - **`## Discriminating probe (the proposed change)`** — what each top hypothesis
     predicts, the single-variable change (with exact value), and what result
     confirms which hypothesis.
   - **`## How to run (for the human — NOT auto-executed)`** — the concrete command
     delta from the profile's `launch.sh` (e.g. "set `payload_cog_offset_xy_radius`
     0.08 → 0.05, all else identical to <baseline run>"). State plainly that
     exp-design did NOT launch it.
   - **`## Status: pending approval`** — the hard gate. The human must approve
     before any run.
   - Keep every numeric claim traceable to a finding's evidence (carry the
     `[EVIDENCE: ...]` source through). No new numbers you did not get from the
     report / code-exec.
4. Write it into the permanent tree THROUGH the core's atomic writer so the path
   comes from the getter AND the proposals dir is created:

   ```bash
   python3 - <<'PY'
   from omx_core.omx_paths import OmxPaths, atomic_path
   p = OmxPaths(root="<root>").proposal_md("<output_root>", "<run_id>", "<proposal_id>")
   with atomic_path(p) as tmp:
       tmp.write_text(r"""<the full proposal markdown you assembled>""")
   print(p)
   PY
   ```

## Hard constraints (never violate)

- NEVER launch training or eval. exp-design only WRITES a proposal. No `launch.sh`,
  no live eval_dr, no `omx eval` against a live run. (design D4/B8 — the repo rule
  "훈련 종료/시작은 유저가 직접" has no override path here.)
- NEVER write a path by hand; the proposal path comes from `proposal_md(...)` and
  the write goes through `atomic_path`. `proposal_id` = `<YYYYMMDD-HHMMSS>-next`.
- NEVER invent a finding or a number. Every claim traces to a `report.md` finding
  (read via `omx report-parse`) or its `[EVIDENCE: ...]` source. If the report has
  no finding supporting a lane, say that lane is unsupported — do not manufacture one.
- The probe changes ONE variable (repo minimum-change rule) so the next run is not
  confounded.
- Respond to the user in Korean (repo rule); keep the proposal markdown / code in English.

## When done

Tell the user where the proposal is
(`<output_root>/<run_id>/proposals/<proposal_id>.md`), summarize the leading
hypothesis and the one-variable probe in 2-3 lines, and remind them it is
**pending approval — not launched**. Do not start a loop or run anything; the
analyze→design→eval loop is exp-loop's job (#6).
