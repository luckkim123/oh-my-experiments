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
   (Calibration: if the user's opening description already names a metric axis, start Constraints ~0.3; if it already names a command + numeric threshold, start Criteria ~0.5.)
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
  Supply `--cv-field` with the primary metric the user named in the Criteria dimension;
  if omitted the CLI default is `ss_error`.

This is read-only grounding; it writes nothing. If no data exists yet, proceed with the
interview on the user's stated intent alone.

## When the gate clears (`ambiguity ≤ 0.2` or early exit): build the profile

Do NOT write profile files yourself. Assemble the interview result into a `metrics.yaml`
dict and shell the Claude-free core verb, which validates and atomic-writes it:

1. **Assemble the metrics dict** from the interview (these keys match the locked schema):
   ```jsonc
   {
     "pending_approval": true,
     "output_root": "<the permanent-tree root the user chose; default 'experiments'>",
     "metrics": ["<closed metric vocab from the Constraints dimension>"],
     "views": ["trajectory", "per_axis_bar", "overlay"],
     "aggs": ["by_axis", "mean_std"],
     "sources": ["eval_summary"],
     "run_id_regex": null,
     "keep_policy": "<pass_only | score_improvement — from the Criteria dimension>",
     "score_formula": null
   }
   ```
   `score_formula` rule: under `pass_only` it MUST be JSON `null` (the literal null,
   not the string `"null"`). Under `score_improvement` it MUST be a real non-empty
   string — the formula you elicited in the interview (e.g. `mean(ss_error) + 0.5*cv(ss_error)`);
   the core loud-fails if it is null/empty under score_improvement (B5).

   Every list entry must be a lowercase token (`[a-z0-9_]`, no `__`); the core will loud-fail
   otherwise (and you should re-ask rather than mangle the user's word).

2. **Resolve the anchor root (H4).** Default to the cwd. If the user gave `--root`, use it.
   `.omx/` lives at this anchor, independent of `output_root` (which is stored *inside*
   metrics.yaml and may point elsewhere).

3. **Shell `omx init`** with the assembled dict as JSON:
   ```bash
   omx init --root "<anchor>" --profile-name "<profile-name, default isaaclab>" \
       --metrics-json '<the JSON dict from step 1>'
   ```
   - rc 0 → it prints `{"written": [...], "pending_approval": true, ...}`.
   - rc 2 → it loud-failed (schema violation, existing profile, unknown reference). Read the
     message: on "already exists", ask the user whether to re-run with `--force` (never pass
     `--force` without asking — the existing profile is their tuning). On a schema error, fix
     the offending field WITH the user and retry.

## Present the profile + the pending-approval gate (this is the stopping point)

After a successful `omx init`, present the four files for review and STOP. Do not proceed to
any analysis, design, eval, or training:

```
Profile bootstrapped (pending approval) at <anchor>/.omx/profile/:
  - evaluator.sh   — seeded from the <profile-name> reference (edit the STUB block for your eval)
  - metrics.yaml   — <one-line summary: output_root, N metrics, keep_policy>
  - rules.md       — your analysis discipline (fill in Always/Never)
  - launch.sh      — your training command template (exp-init never runs it)

Next steps (yours, not mine):
  1. Edit evaluator.sh — replace the STUB with your real eval command.
  2. Fill rules.md + launch.sh.
  3. Set pending_approval: false in metrics.yaml (or delete the key) to approve.
Once approved, run exp-analyze on your runs.
```

**Hard gate (mirrors deep-interview's approval gate):** until the user explicitly approves
(edits `pending_approval` to false, or says so), `exp-init` MUST NOT invoke exp-analyze,
exp-design, exp-loop, or any mutation/execution skill, and MUST NOT run training or eval. The
profile is a *proposal*. This honors the repo rule "훈련 종료/시작은 유저가 직접" with no
override path in v0.1.

## Re-running exp-init

If a profile already exists, `omx init` refuses (rc 2). exp-init then asks whether to
overwrite (`--force`) — overwriting replaces the user's tuning, so it is always an explicit,
confirmed choice, never automatic.
