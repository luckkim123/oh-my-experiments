---
name: exp-init
description: Bootstrap the OMX experiment profile via an interactive ambiguity-gated Socratic interview. Use when setting up experiment-analysis infrastructure for a research project (the "research /init") — elicits the optimization objective, eval method, success criteria, metric vocabulary, and launch recipe, then writes .omx/profile/{evaluator.sh, metrics.yaml, rules.md, launch.sh} marked pending approval. Triggers on "set up experiment analysis", "exp-init", "실험 분석 셋업", "프로파일 만들어".
argument-hint: "[--profile-name <name>] [--root <dir>] <one-line research description>"
---

# exp-init — bootstrap the OMX experiment profile

## Overview

`exp-init` is OMX's "research /init". It runs an **interactive** Socratic interview to
elicit how *this* researcher's experiments should be analyzed, then bootstraps the user
profile that every other OMX skill (exp-analyze/design/loop) reads.

**It writes profile files and NOTHING else.** It never launches training, never runs eval,
never edits source. The four files it produces are labelled `pending approval` — templates
the user reviews and edits before any OMX run consumes them (design D4/B8 — training
launch is never auto-fired).

**Announce at start:** "Using exp-init to interview you and bootstrap the OMX profile."

## What it produces (via the `omx init` core verb — not direct file writes)

`.omx/profile/` (anchored at the cwd or the chosen `--root`, resolved BEFORE output_root — design H4):
- `metrics.yaml` — output_root + metric/view/agg/source vocabulary + keep_policy + score_formula slot
- `evaluator.sh` — seeded from the committed reference (`reference/<profile-name>/evaluator.sh`); user edits the stub later
- `rules.md` — the user's analysis discipline ("CV mandatory", etc.)
- `launch.sh` — the training-command template (NEVER executed here)

All schema validation + atomic writes happen in the tested Python core (`omx init`), not in
this skill — so the structure discipline is enforced by code, not by this skill's diligence.

## The ambiguity gate (re-implemented from deep-interview — pattern, not import)

OMX reuses deep-interview's proven 3-dimension weighted gate. **Do not invent a new
5-dimension vector** — map the 5 experiment topics onto the 3 dimensions:

| Dimension (weight) | exp-init topics folded in | What "clear" means |
|:--|:--|:--|
| **Goal (0.40)** | objective | One quantity + direction stated without qualifiers |
| **Criteria (0.30)** | eval-method + success-criteria + score-formula | A command produces the verdict AND a numeric threshold defines success |
| **Constraints (0.30)** | metrics (axes/vocab) + launch-recipe (GPU/command) | The metric axes are enumerated AND the exact training command + GPU gate are stated |

**Ambiguity formula (greenfield):**
```
ambiguity = 1 − (goal·0.40 + criteria·0.30 + constraints·0.30)
```
Each clarity score is in `[0.0, 1.0]`. **Threshold = 0.2** (proceed to profile-write when
`ambiguity ≤ 0.2`). Soft warning at round 10; hard cap at round 20 ("proceeding with current
clarity"). The user may exit early from round 3+ ("enough", "build it", "go").

## Interview loop (ONE question per round — interactive, human answers every round)

This is the interactive part (H2) — NOT autonomous. Loop until `ambiguity ≤ 0.2` OR early exit:

1. **Score the three dimensions** from what's known so far (start all at ~0.0, or higher if the
   initial description already pins a dimension). Compute `ambiguity`.
2. **Target the weakest dimension.** Generate ONE question that most reduces its ambiguity.
   Use the sample gating questions:
   - Goal: "What single quantity should the next experiment move, and in which direction?"
   - Criteria: "What command produces the pass/fail verdict, and what numeric threshold = success?"
   - Criteria (score-formula, D5): surface any existing run data — "Your past runs show
     ss_error mean X with CV Y; should success aggregate by mean, mean+λ·CV, or per-axis
     worst-case?" (only ask if keep_policy will be score_improvement).
   - Constraints: "Which metric axes matter (give the closed list), and what is the exact
     training command + GPU gate?"
3. **Ask using the prose-option protocol** (see below). Wait for the human's answer.
4. **Re-score** the targeted dimension from the answer; recompute `ambiguity`.
5. **Report progress** in one line: `Round {n} | targeting {dim} | ambiguity {pct}%` then the question.
6. Repeat.

### Prose-option protocol (AskUserQuestion is NOT used)

This skill does **not** call `AskUserQuestion` (it presents questions as prose for portability).
Each round, present:

```
Round {n} | {dimension} | ambiguity {pct}%
{the question}

  [1] {concrete option A}
  [2] {concrete option B}
  [3] (other — describe in your own words)
```

The user replies with a number or free text. Offer concrete options drawn from any existing
data you can read (see "Grounding in existing data" below), but always allow free text — never
force a choice. If the answer is itself ambiguous, that dimension's clarity stays low and you
ask a sharper follow-up next round.

### Grounding in existing data (optional, strengthens the Criteria dimension)

Before/while interviewing, you MAY read existing experiment data to offer concrete options and
to ground the score-formula question — using ONLY the Claude-free core verbs (never invent paths):
- `omx ingest --path <eval summary.json> --format eval_summary` — see what metrics/axes exist.
- `omx reduce summarize --path <...> --format eval_summary --cv-field <metric>` — get mean/std/CV
  to inform the mean-vs-CV-vs-worst-case score-formula choice (D5).

This is read-only grounding; it writes nothing. If no data exists yet, proceed with the
interview on the user's stated intent alone.
