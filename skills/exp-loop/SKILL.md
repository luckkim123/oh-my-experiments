---
name: exp-loop
description: Run a semi-autonomous experiment loop — analyze the latest run, design the next experiment, evaluate a candidate, keep or discard it, log the decision, and repeat until a deadline or a stop condition. The "leaving-work" deadline governs only the analyze/design/eval phases; the next TRAINING LAUNCH is queued as a pending-approval artifact and NEVER auto-fired. Use when the user says "run the analyze→design→eval loop", "퇴근할 거니까 알아서 분석하고 다음 실험까지 큐에 넣어둬", "iterate on this experiment automatically", "keep evaluating candidates and keep the best". Triggers on "experiment loop", "auto-iterate", "다음 실험까지 돌려놔", "loop until".
argument-hint: "[--root <dir>] <run_id> [--max-runtime <seconds>]"
---

# exp-loop — semi-autonomous analyze→design→eval→keep/discard→log loop

## Overview

`exp-loop` chains the OMX skills into one supervised loop over a single run:

```
analyze (exp-analyze) -> design (exp-design) -> evaluate candidate (omx eval)
   -> keep/discard (a decision via the core engine) -> log the iteration (ledger)
   -> queue the next launch (pending approval) -> STOP for human, or repeat
```

It NEVER launches training (design D4/B8). The "leaving-work" deadline is a
ceiling on the AUTONOMOUS phases (analyze/design/eval). The next training run is
always written to `runs/<run_id>/pending-launch.json` as `pending approval` for
the human to fire by hand. This honors the repo rule "training stop/start is done
by the user directly" with no override path.

**Announce at start:** "Using exp-loop to run the analyze→design→eval loop; training launch will be queued for your approval, never fired."

## Preconditions (check, don't assume)

0. Step-0 preflight: `omx doctor --root <root>` — a stale/missing install fails
   actionably here instead of surfacing as a confusing error mid-loop.
1. A profile exists at `.omx/profile/` (run `exp-init` first if not). You need
   `metrics.yaml` (for `output_root` + the metric vocabulary) and `evaluator.sh`
   (the eval command) — both written by exp-init.
2. A `run_id` is given (the experiment to iterate on). If absent, ask for it and STOP.
3. The run has at least one analyzable result (an eval summary / training log the
   profile's adapters can ingest). If there is nothing to analyze, say so and STOP.

If any precondition is unmet, state exactly what is missing and STOP. Never
fabricate a run or invent an evaluator.

## Session id (scratch isolation, B2)

Resolve a session id once: `omx session-id` (it applies `--session-id` flag →
`OMX_SESSION_ID` env → autogen). Pass it to exp-analyze when you delegate.

## The deadline ceiling (the "leaving-work" toggle)

If the user gives `--max-runtime <seconds>` (or says "퇴근할 거니까"), the loop
runs autonomously until that ceiling (e.g. the user says "I'm leaving work, so analyze on your own and queue up to the next experiment"). You do NOT compute the deadline yourself —
the core does it. BEFORE each iteration, ask the CLI for the loop status, passing
the run's `--max-runtime` (the CLI computes `deadline = now + max-runtime` and
reports whether it has passed):

```bash
omx loop-status --root <root> --run-id <run_id> --max-runtime <seconds>
```

If its JSON shows `"deadline_passed": true`, STOP the autonomous loop (do NOT
start another analyze/design/eval pass). The deadline NEVER triggers a launch —
it only stops analysis. With no `--max-runtime`, run exactly ONE iteration then
stop and report (a single supervised pass is the safe default).

### Arm the Stop-hook gate (persistent mode)

Once the user approves the max-runtime, arm the gate so the session keeps
cycling even when a turn ends early:

    omx loop-arm --run-id <run_id> --max-runtime <seconds> --session-id <session_id> --root <root>

State this to the user when arming (ownership is intended, not incidental):
**arming dedicates this session to the loop until `omx loop-disarm`** — every
turn-end is continued by the gate, including off-topic turns. The gate
self-expires at the deadline and after 50 blocked stops (hard cap), and
`OMX_SKIP_HOOKS=loop_gate` / `OMX_DISABLE=1` silence it instantly. Arming
fails loudly if a loop is already armed for this root — disarm first.
Pass the `--session-id` you resolved above (the "Session id" section): the arm
claims a per-run lease keyed by that id, so `omx run-record --session-id
<session_id>` can later prove this session owns the run (a stray record from
another session loud-fails).

## One iteration

### 1. Analyze
Delegate to `exp-analyze` for `<run_id>` (it writes `report.md` + promoted plots
to the permanent tree and emits evidence-tagged findings). Capture the
`analysis_id` it reports.

### 2. Design
Delegate to `exp-design` with that `report.md` (`<run_id>` + `<analysis_id>`). It
runs the 3-lane diagnosis and writes a `proposals/<proposal_id>.md` (the
discriminating probe = the next experiment), `pending approval`. Capture the
`proposal_id`.

### 3. Evaluate the current candidate (if one exists)
A "candidate" here is an already-trained checkpoint the human produced for this
run (exp-loop does NOT train). If the profile's `evaluator.sh` can grade the
current checkpoint, run it through the core (this is the single source of the
pass/score verdict — never eyeball a metric):

```bash
omx eval --root <root> --command 'bash .omx/profile/evaluator.sh' --cwd <project_dir> \
    --keep-policy <pass_only|score_improvement> --last-kept-score <prev_or_omit>
```

`--root` enables the seal preflight (#0): a sealed evaluator that was modified mid-loop
rc-2s instead of silently regrading; re-approve intentional changes with
`omx profile-seal --root <root>`.

The JSON includes a `decision` block (`keep`/`discard`/`ambiguous`/`bootstrap`)
when `--keep-policy` is set. That decision is authoritative. If there is no new
candidate to grade (e.g. this is the very first analysis pass), skip evaluation
and go straight to queuing the next launch.

### 4. Record the iteration (keep/discard target = B6)
The core applies the keep/discard pointer rule inside the ledger. Record this
iteration through the ledger writer — on the FIRST iteration seed the ledger,
then record every iteration:

First iteration only (once): seed the ledger with the pre-experiment anchor:

    omx run-seed --run-id <run_id> --baseline-commit <baseline_sha> \
        --keep-policy <pass_only|score_improvement> --root <root>

Every iteration: record the decision (pass the eval JSON you saved in step 3 so
the evaluator block is embedded, the owning session id so the lease is asserted,
and the project cwd so the git-ancestry staleness check runs — a candidate
trained from a commit BEHIND the kept line loud-fails):

    omx run-record --run-id <run_id> --iteration <n> --decision <keep|discard|ambiguous|bootstrap> \
        --candidate-checkpoint <path> --candidate-commit <training_head_sha> \
        --description "<one line>" --session-id <session_id> --cwd <project_dir> \
        --eval-json <saved eval output> --root <root>

`run-record` prints the updated pointer trio (`last_kept_commit`,
`last_kept_checkpoint`, `last_kept_score`) + the appended entry. You do NOT
git-revert or delete any checkpoint yourself — the ledger pointer + decision-log
is the record; physical checkpoint GC is out of scope (design §9).

If a config edit was made and the decision is `discard`, offer the mechanized
revert — but keep it human-gated. Show the user the dry-run plan first:

    omx revert-config --cwd <project_dir> --run-id <run_id> --to baseline --root <root>

This prints `would_revert` (the exact files a revert would touch; `.omx/` run
artifacts are always protected). Only on the user's explicit approval, apply it:

    omx revert-config --cwd <project_dir> --run-id <run_id> --to baseline \
        --i-approve-revert --root <root>

NEVER pass `--i-approve-revert` without the user's explicit "yes" — the dry-run
is what they approve (minimum-change revert, never-auto-git repo rule).

- On keep: `omx tree-alias --name latest --run <run_id>` — explicit only; no
  alias is ever re-pointed automatically.
- Record the decision in the campaign ledger: `omx campaign-log --id <group>
  --event <kept|discarded> --run <run_id>
  --data '{"proposal_id": "<proposal_id>", "reason": "..."}'`
  (campaign id = the run's group segment; init once with `omx campaign-init`).
  The `proposal_id` is the one captured in step 2 — it MUST be in `--data`:
  `campaign-status` resolves a planned proposal to kept/discarded by joining
  on exactly this key, so an outcome event without it leaves the proposal
  stuck at `planned` forever.

### 4.5 Circuit check (stop a churning loop)

After recording, ask the ledger whether the loop is making progress:

    omx loop-health --run-id <run_id> --root <root>

It prints the streaks and trip flags. If it exits rc 2 (a plateau of consecutive
discards, or a streak of evaluator faults), STOP the loop — this is the
AUTHORITATIVE stop path. Disarm with the matching reason and report the streak
to the user:

    omx loop-disarm --reason plateau --root <root>        # (or --reason fault_circuit)

The Stop-hook gate also self-disarms on the same signal as a backstop, but the
verb is what you act on — a churning loop wastes the deadline it was given.

### 5. Queue the next launch (NEVER fire it — B8)
Mint the run skeleton first: `omx tree-scaffold --run-id <id> --under <levels>
[--data-dir <logs dir>]` — grammar/tag violations and existing leaves are
refused at mint time (F8/F4); nothing is launched.

The proposal from step 2 is the next experiment. Queue it for human approval:

```bash
omx queue-launch --root <root> --run-id <run_id> \
    --proposal-id <proposal_id> \
    --launch-delta "<the one-line change vs profile launch.sh, from the proposal>" \
    --gpu-gate "<the nvidia-smi precondition, e.g. 'GPU0 free per nvidia-smi'>"
```

This writes `runs/<run_id>/pending-launch.json` marked `pending approval`. STOP
here for the launch. You have NOT trained anything. Tell the user the proposal +
the queued launch, and that THEY must approve and run the training command.

### 6. Audit the wiki at iteration end (report-only, never auto-fix)

At the end of each iteration, audit the accumulated wiki so stale/orphaned/broken
knowledge surfaces (it is review-gated - you report, the human decides):

First capture the iteration's findings as breadcrumbs (idempotent):
`omx wiki capture-session --root <root> --from-report <this iteration's report.md> --run-id <run_id>`

`omx wiki lint --root <root>`

Report any `stale` / `broken-ref` / `broken-frontmatter` / `orphan` /
`low-confidence` / `contradiction-candidate` issues to the user in your summary.
Do NOT auto-edit or delete any page (minimum-change / review-gated rule).

Before writing the iteration close-out summary, reconcile the open backlog:
`omx wiki list --status needs-experiment --root <root>` (and
`--status needs-apply-before-retrain`). Every open lead must be present in your
"next" section or explicitly deferred with a reason — silently dropping a lead
that the wiki flags is the backlog-flatten defect. An open
`needs-apply-before-retrain` gate must be named as a launch prerequisite, never
omitted from the delta list.

If `lint`'s `stats.by_type` shows several `info`+ issues (orphan / stale /
contradiction-candidate accumulating), add a one-line cleanup reminder to the
summary: "wiki cleanup review suggested — run `omx wiki gc --root <root>` to see
delete candidates (orphans) and a ready-to-edit proposal skeleton." This only
SURFACES the suggestion; the human reviews and approves any `gc-apply` (the
git-guarded executor). NEVER run gc-apply automatically.

### 7. Loop or stop
If a deadline is set and `omx loop-status` says it has NOT passed AND there is a
fresh candidate to analyze next, repeat from step 1. Otherwise STOP.

When you decide to STOP (deadline passed, work done, or the user says stop),
disarm the gate FIRST so the Stop hook lets the session rest:

    omx loop-disarm --reason done --root <root>

Deadline expiry needs no action — the gate self-disarms on the next stop.

Use the reason that matches WHY you stopped: `done` (work complete), `cancel`
(user asked), `plateau` / `fault_circuit` (a `loop-health` trip) — the reason is
recorded in the completion marker and the campaign forensics.

## Hard constraints (never violate)

- NEVER launch or start a training run. exp-loop only QUEUES launches via
  `omx queue-launch`. No `bash launch.sh`, no training subprocess, ever (D4/B8).
- NEVER auto-run a `git revert`/`git reset`/`rm` on weights or config. Surface
  the exact command; the human runs it (minimum-change revert rule).
- NEVER hand-write a `.omx/` path. Queue/status/eval all go through the `omx`
  CLI verbs, which resolve paths via the core (path-SSOT).
- NEVER invent a verdict. The pass/score decision comes ONLY from `omx eval`'s
  JSON (the evaluator contract), and the keep/discard from its `decision` block.
- The deadline ceiling gates ONLY analyze/design/eval — it is NEVER a launch
  trigger.
- NEVER auto-fix, edit, or delete a wiki page from a lint result. lint is
  report-only; the human decides any change (review-gated).
- Respond to the user in the user's language / the machine's locale language (repo rule); keep skill/code/markdown in English.

## When done

Report, in the user's language, to the user:
- where the analysis report and proposal are (permanent tree paths),
- the keep/discard decision(s) and the reason (from the decision-log),
- that the next launch is QUEUED at `runs/<run_id>/pending-launch.json` as
  **pending approval — not launched**, and the exact training command they should
  run after approving.
- Confirm the gate is disarmed: `omx loop-status --run-id <run_id> --root <root>`
  must report `"armed": null`. A dangling armed loop hijacks the next session's
  stops until its deadline.
- If a campaign id is set for this work, optionally dispatch the
  `campaign-auditor` agent (read-only) on the campaign ledger and surface its
  findings to the user before closing out.

This is the last skill in the OMX set. There is no successor loop to start.
