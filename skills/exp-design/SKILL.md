---
name: exp-design
description: Design the next experiment from an exp-analyze report. Use after analyzing runs, when you need to decide what to change next — runs a 3-lane differential diagnosis (code-path / config-DR-hyperparam / measurement-artifact) over the evidence-tagged findings and proposes the single discriminating probe (the next-experiment config) as a pending-approval artifact. Reads report.md, writes proposals/<id>.md — this proposal IS the deliverable, so any request to "make/write a proposal for the next experiment" is exp-design. Never launches training or eval. Triggers on "design the next experiment", "what should I change next", "diagnose why this regressed and propose a fix experiment", "write a proposal for the next run", "what experiment next", "다음 실험 설계", "다음에 뭘 바꿔야 할까", "다음 실험 제안해줘", "next 실험 proposal 만들어줘".
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

0. Step-0 preflight: `omx doctor --root <root>` — a stale/missing install fails
   actionably here instead of surfacing as a confusing error mid-design.
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

## Query the wiki for prior diagnoses of this symptom

Before the diagnosis, check whether the workspace already diagnosed this symptom
(avoids re-deriving a known cause / re-proposing a tried probe):

`omx wiki query --root <root> "<the symptom you are diagnosing>" --category decision`
`omx wiki query --root <root> "<the symptom you are diagnosing>" --category pattern`

These two categories are queried for a reason: `decision` holds why a cause was
adopted/discarded with the data that decided it (= a past confirmed cause), and
`pattern` holds recurring metric behaviours (= the shape this symptom tends to take).
`debugging` (a reusable diagnostic procedure) is also worth a query when the symptom is
unfamiliar. exp-analyze writes these via its auto-capture loop, so the more the
workspace is analyzed, the more this query returns.

Also enumerate the open backlog keyword-independently — a symptom-scoped query alone
hides leads the workspace already flagged as needing an experiment:
`omx wiki list --status needs-experiment --root <root>` (and
`--status needs-apply-before-retrain` for HARD corrections that must be applied before
any retrain). This is the "look at the wiki for what needs experimenting" enumeration
that a ranked query cannot surface; weigh those leads when choosing the next probe.

Treat hits as PRIOR EVIDENCE feeding the diagnosis (a past confirmed cause is strong
evidence for that lane). If a prior probe was already tried, design a DIFFERENT
discriminating probe. An empty result just means this is new ground.

### Check the campaign plan (do not re-propose a settled probe)

If this run belongs to a campaign, read its reconciled plan before designing:

    omx campaign-status --id <group> --root <root>

Its `plan` list carries each planned proposal with a `derived_status`
(`planned` / `launched` / `kept` / `discarded`, joined against the ledger at
read time). Do NOT re-propose a probe family already marked `discarded` (it was
tried and rejected) or still `planned` (it is queued) — feed this mechanical
signal into the novelty judgment `probe-novelty` also informs.

### Recipes (promoted procedures)

Also list `.omx/recipes/` — a recipe matching the regression's symptom
prescribes the discriminating checks a past diagnosis validated. Follow it as
a checklist before inventing a new probe; cite it in the proposal.

## Act on engine-gap specs (close the engine self-specialization loop)

exp-analyze records ENGINE-GAP SPECS — code-change specifications for the analysis
engine. The engine is ALL the ANALYSIS code this workspace owns (code that READS results
without changing them): both the reference adapter the profile points at (`.omx/profile/`)
AND the workspace's own pure post-processing source (e.g. an `analysis/` package that reads
saved `*.npz`/`summary.json`). They are the write half of "the engine specializes the more
the workspace is used"; this is the read half. Before designing the probe, surface any open
specs:

`omx wiki query --root <root> "engine-gap" --category decision`

For each hit with `[STATUS] proposed` that is RELEVANT to the symptom you are diagnosing
(it would let the engine actually diagnose this case): implement it as a SMALL, surgical
change at the `[WHERE]` it names (the profile adapter, or the workspace's post-processing
source — whichever the spec points at), following its `[SPEC]`. Then flip that wiki page to
`[STATUS] implemented` (append a dated note via `omx wiki add` — append-only merge). This
makes the engine sharper for THIS workspace each cycle, exactly as intended.

Boundaries (do not overreach) — the line is READS-results vs PRODUCES-results, not where the
file lives:
- IN scope: ANALYSIS code that reads results without changing them — the `.omx/profile/`
  adapter AND the workspace's pure post-processing source (metrics, plots, comparison,
  heavy-tail/divergence stats). A spec may also create a NEW analysis module if `[WHERE]`
  says so.
- OFF LIMITS: the harness's own core and skills (never edit the harness itself); and any
  experiment-determining source — model / reward / training / env code, anything whose
  change would alter the results themselves. That is what the probe proposes, separately;
  it is NEVER an analysis-time edit. When unsure whether a file "reads" or "produces"
  results, treat it as produces (off limits) and leave the spec `proposed`.
- Implement only specs whose `[SPEC]` is concrete enough to act on safely; leave vague or
  irrelevant ones `proposed`.
- Still NEVER launch training or eval. This step edits analysis code, nothing that runs the
  experiment. (If the analysis file you touch ALSO contains run/eval-launch code — e.g. an
  Isaac-Sim eval runner — change only the pure post-processing parts, never the launch path;
  if they cannot be separated cleanly, leave the spec `proposed` and flag it for the user.)
- If no engine-gap specs are open, skip this step — it is opportunistic, not required.

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

Write the two predictions as MACHINE-CHECKED tag lines inside the
`## Discriminating probe` section (the lint gate reads them):

    [H1-PREDICTS] <what the leading hypothesis predicts the probe outcome to be>
    [H2-PREDICTS] <what the strongest alternative predicts — MUST differ from H1>

The discriminating probe, expressed as a concrete change to the training/eval
setup, IS the proposed next experiment. It is a PROPOSAL — never run it.

## Step 4 — write the proposal (permanent tree, via the core — never hand-write paths)

1. Choose a `proposal_id` = `next-<YYYYMMDD-HHMMSS>` (the verb is literally `next`,
   FIRST, so names read label-before-date consistently). Get the timestamp from
   `date +%Y%m%d-%H%M%S` via Bash and prefix the verb: `next-$(date +%Y%m%d-%H%M%S)`.
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
     confirms which hypothesis, including the [H1-PREDICTS]/[H2-PREDICTS] tag lines.
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

## Step 5 — independent review (author != reviewer — spec 2.5)

The proposal is NOT final until a fresh reviewer has seen it. After writing
proposals/<id>.md, dispatch the `proposal-reviewer` agent (read-only) with the
proposal path and the workspace root. It runs `omx proposal-lint` +
`omx probe-novelty` first, then judges discrimination / one-variable /
provenance, and returns `{"verdict": "approve"|"revise", ...}`.

- `approve` -> present the proposal to the user as pending-approval (unchanged
  hard gate: the HUMAN decides whether the experiment runs).
- `revise` -> address every major issue by RE-WRITING the proposal through this
  skill's Step 4 (a new proposal artifact, never a hand-edit of the reviewed
  one), then re-dispatch the reviewer. Do not present a `revise`-verdict
  proposal to the user as ready.

Never self-approve: the session that authored the proposal must not skip the
reviewer because the proposal "looks obviously right" — that is exactly the
failure mode this step exists to stop.

## Hard constraints (never violate)

- NEVER launch training or eval. exp-design only WRITES a proposal. No `launch.sh`,
  no live eval_dr, no `omx eval` against a live run. (design D4/B8 — the repo rule
  "훈련 종료/시작은 유저가 직접" has no override path here.)
- NEVER write a path by hand; the proposal path comes from `proposal_md(...)` and
  the write goes through `atomic_path`. `proposal_id` = `next-<YYYYMMDD-HHMMSS>`.
- NEVER invent a finding or a number. Every claim traces to a `report.md` finding
  (read via `omx report-parse`) or its `[EVIDENCE: ...]` source. If the report has
  no finding supporting a lane, say that lane is unsupported — do not manufacture one.
- The probe changes ONE variable (repo minimum-change rule) so the next run is not
  confounded.
- Respond to the user in the machine's locale language / the user's language (repo rule); keep the proposal markdown / code in English.

## When done

Before reporting, gate the proposal:
`omx proposal-lint --path <proposals/<id>.md>` MUST exit 0 (fix the proposal
through a re-write if it fails — the H1/H2 predictions must genuinely differ), and run
`omx probe-novelty --path <that path> --root <root> --proposals-dir <output_root>/<run_id>/proposals`
— surface any overlap warning to the user (novelty is their judgment call, not a gate).

Tell the user where the proposal is
(`<output_root>/<run_id>/proposals/<proposal_id>.md`), summarize the leading
hypothesis and the one-variable probe in 2-3 lines, and remind them it is
**pending approval — not launched**. Do not start a loop or run anything; the
analyze→design→eval loop is exp-loop's job (#6).
- Record the adopted proposal as campaign INTENT (replayable plan, not an
  outcome): `omx campaign-plan-add --id <group> --proposal-id <proposal_id>
  --summary "<one-line probe>" --label <short-handle>`. The campaign ledger's
  `note`/`kept`/`discarded` events still record what HAPPENS to the proposal
  later (via exp-loop); this line records that it was PLANNED. Give every
  planned proposal a short `--label` (C2-style) — the label is the handle
  humans will use in prose; without it, parallel ad-hoc id schemes appear.
  The `launched`/`analyzed` events are auto-recorded later as byproducts of
  `queue-launch`/`report-coverage` — nothing further to do here.
