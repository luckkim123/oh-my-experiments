---
name: exp-analyze
description: Analyze N existing experiment/training runs into an evidence-tagged report. Use when comparing runs, reading eval/training curves, or diagnosing why a run regressed — the hybrid router decides per question whether to use exact code-exec stats, a vision-read PNG curve, or both. Reads the OMX profile (metrics.yaml) for the metric vocabulary. Writes report.md + promoted plots into the permanent analysis tree — this report IS the deliverable, so any request to "make/write a report on these runs" is exp-analyze, not a hand-written summary. Never launches training or eval. Triggers on "analyze these runs", "compare run A and B", "why did this regress", "make a report on this run", "write up these results", "런 분석", "eval plot 보여줘", "리포트 만들어줘", "이 런 report 만들어줘", "결과 정리해줘".
argument-hint: "[--root <dir>] [--no-wiki] <run ids or result paths to analyze>"
---

# exp-analyze — hybrid PNG-vision + code-exec run analysis

## Overview

`exp-analyze` analyzes results that ALREADY EXIST. It never launches training or
eval (design D4/B8). It reads the OMX profile written by exp-init, then runs the
hybrid router (design §5) to answer each analysis question with the cheapest
sufficient evidence, and writes a single human deliverable: `report.md` (+ the
plots it references) in the permanent analysis tree.

**`report.md` in the analysis tree is OMX's canonical analysis output.** When the
user asks to "make a report" on a run, this is what they get — do NOT reach for a
hand-written summary, and do NOT conclude "a report already exists" just because the
run folder or some project doc holds other notes. A pre-existing eval/summary file is
INPUT to exp-analyze, never a substitute for its `report.md`. Producing this report is
exp-analyze's reason to exist; if you are unsure whether OMX "can make a report", the
answer is yes and this skill is how — verify by reading this file, not by scanning the
`omx` CLI verb list (report authoring lives in the skill layer, not as a CLI verb).

**Announce at start:** "Using exp-analyze to analyze the runs and write an evidence-tagged report."

## Preconditions (check, don't assume)

1. A profile exists and is approved. Read `<root>/.omx/profile/metrics.yaml`. If it
   is missing → tell the user to run exp-init first; STOP. If `pending_approval: true`
   is still set → tell the user to approve it first; STOP. (Honors the exp-init hard gate.)
2. The runs to analyze exist on disk. The user names run ids or result paths
   (eval_dr summary.json, TB event files, wandb run dirs, data_*.npz). Resolve them;
   if a path is missing, say so and STOP — never fabricate data.

## Run the profile's diagnostic engine — MUST, not MAY (the engine-skip anti-pattern)

If the profile points at a training-log diagnostic engine — a `.omx/profile/*.py`
script recorded as a reference adapter (find it: `ls .omx/profile/*.py` and the wiki
page tagged `engine`/`adapter`, e.g. `training_log_analysis_engine_reference_adapter`)
— you **MUST run it on each training run** and ground the report in its output
(its `[DIAGNOSIS]` / `[TREND]` / changepoint / plateau / regime lines), not just in
final scalars you read off the curve. Run it, e.g.:

`ALBC_LOGS_ROOT=<logs/rsl_rl> python3 .omx/profile/analyze_training.py <run-path> --tier 3 --deep`

Hand-extracting FINAL SCALARS from raw TB/wandb **instead of** running the engine is
the exact anti-pattern this skill forbids (it is what produced a count-looks-fine but
diagnosis-empty report; cf the `omx-route-must-invoke` discipline — declaring the omx
lane is a commitment to invoke the engine, not to hand-read curves). The engine's
time-series diagnosis (phase/plateau onset, PELT changepoints, HMM regime, lead-lag)
CANNOT be reconstructed from end-of-run values. If you deliberately choose not to run
it for a given run, the report MUST state why, per run. The completeness gate in
"When done" enforces this (`omx report-coverage`).

This is about USING the engine, not editing it: growing/specializing the adapter is a
separate, optional activity (see "Record engine-gap specs"); running it during analysis
is mandatory.

## Verify the engine's output — an empty cell is a HYPOTHESIS, not a fact (the engine-output-unverified anti-pattern)

Running the engine is necessary but NOT sufficient. The engine can run cleanly and
still print `0` / `()` / an empty table for a metric group **because its tag-naming
assumption missed how THIS workspace logs** — not because the data is absent. Trusting
that empty cell as "no data" and copying it into the report (or worse, concluding "the
engine can't produce X") is the second failure mode this skill forbids.

**엔진의 빈 셀은 가설('도구가 그 tag를 못 찾음')이지 결론('데이터 없음')이 아니다.**
(This is the repo's `verify implementation, not name` + `no premature assertion` rules
applied to a tool's output: the engine's *name* for a group says nothing about whether
the group's *tags exist*.)

So whenever the engine reports a diagnostic group as `0` / empty / absent (e.g.
`constraints=0`, an empty constraint table, "no reward decomposition"), **cross-check
the raw TB before asserting absence**:

1. **Dump the raw scalar tag set.** With the TB event file in hand:
   ```python
   from tensorboard.backend.event_processing import event_accumulator
   ea = event_accumulator.EventAccumulator(str(ev), size_guidance={event_accumulator.SCALARS: 0})
   ea.Reload(); tags = ea.Tags()["scalars"]
   ```
   Grep `tags` for the group's prefix (e.g. `Constraint/`, `Reward/`). 
2. **If the tags EXIST** → the engine's prefix/naming assumption is wrong, not the data.
   - Pull the values yourself with `omx reduce tb-final --path <ev> --format tensorboard
     --tag <T> ...` (named final-window means, a code-exec source you can cite) — do NOT
     hand-average a curve. Put the real numbers in the report.
   - Record an **engine-gap spec** (see "Record engine-gap specs") naming the tags the
     engine failed to scan, so the adapter gets fixed in a later session.
3. **Only if the tags are genuinely ABSENT** may you write "the run did not log X".

This is exactly how the dr-harder report failed even with the engine run: it printed
`constraints=0` + no reward decomposition, the agent copied that as truth, and wrote a
false "reward 8-term decomposition unavailable" conclusion — while the TB held all 8
`Reward/*` tags and 21 `Constraint/*` tags the engine's `cost_return_*` scan never saw.

## Ground in prior workspace knowledge (query the wiki — TWO passes)

Before analyzing, pull accumulated knowledge so you do not re-derive what the
workspace already learned. Query in TWO passes, because a conclusion-only search
hides the workspace's own TOOLING — the dr-harder incident skipped the diagnostic
engine precisely because a single symptom query (`"SS error attitude DR"`) never
surfaced the engine's how-to page (its tags are `adapter`/`analyze`/`engine`, which
share no vocabulary with a symptom query).

- **Pass A — discover the analysis TOOLING this workspace owns.** Query for the
  tools/engines first:
  `omx wiki query --root <root> "analysis engine reference adapter how to analyze"`
  Read what diagnostic engine / post-processing the workspace already has, so you
  run it (see the MUST above) instead of re-deriving it by hand.
- **Pass B — discover prior CONCLUSIONS about this run's topic.** Then query by the
  run's metric/symptom:
  `omx wiki query --root <root> "<the run's main metric or symptom>"`

Read the returned `matches` (snippets + confidence) as CONTEXT, not as findings to
copy. If `corrupt_pages` is non-empty, mention it (lint will flag them). An empty
result is normal for a fresh workspace.

## Session id (for scratch isolation, B2)

Resolve once at start: `omx session-id --session-id "<claude session id if known>"`.
Pass the printed id as `--session-id` to every `omx plot` / `omx promote-plots` call
so this analysis's candidate plots stay isolated under `scratch/<sid>/plots/`.

## The hybrid router (design §5 — the core IP)

For EACH analysis question, pick the evidence type by the question's nature. Never
put raw CSV/tables in context — that is the failure mode this router prevents.

| Question type | Tool | How |
|:--|:--|:--|
| exact numbers (mean, CV=std/mean, per-axis max, slope, pass/score) | **code-exec** | `omx reduce summarize --path <summary.json> --format eval_summary --cv-field <metric>` → exact JSON. For TB/wandb curves, `omx ingest`/`omx plot` then compute in a scratch script under `scratch/<sid>/py/` (write via the core path, run with python3). |
| shape / convergence point / divergence span / heavy-tail tail | **PNG-vision** | `omx plot --root <root> --session-id <sid> --path <src> --format <fmt> --series <key> --metric <m> --view <v>` → renders a candidate PNG into scratch; then READ that PNG with the vision tool and describe the shape. |
| where two runs diverged (aligned) | **PNG overlay OR code stride-extract** | overlay: plot both series on one figure (visual point); exact iter: stride-extract in a scratch script. |
| one-line verdict (pass/score) | **code-exec → JSON scalar** | `omx eval ...` (only if the profile's evaluator is approved; NEVER auto-launch a live eval — read an existing verdict if present). |

Pipeline discipline: **summary-stat-first → PNG only if it's a shape question →
code-exec to verify any precise claim.** A claim about a number must trace to a
code-exec output, never to eyeballing a PNG (repo rule: no guessing — prove it with code/data).

## Evidence tags (mandatory in report.md — design §1, sciomc pattern)

Every finding is tagged:
- `[FINDING]` — the claim, one line.
- `[EVIDENCE: <source>]` — the file/command that proves it (e.g. `summary.json hard/roll/ss_error=0.76`, or `Reward/total curve, scratch plot`).
- `[CONFIDENCE: HIGH|MED|LOW]` — HIGH = exact code-exec number or a clear PNG shape; MED = inference across sources; LOW = speculation (avoid — prefer to gather more evidence).

A finding with a numeric claim and `[CONFIDENCE: HIGH]` MUST cite a code-exec source, not a PNG.

**D1 — Readable format inside [EVIDENCE] (rule 06 Output Form: parallel items = bullets,
comparisons = tables).** When an [EVIDENCE] block contains 3+ numbers, or compares
multiple axes × DR levels, render it as a line-broken bullet list or a markdown table —
never a single wall-of-text paragraph. One [EVIDENCE] = one bullet list or table, not a
run-on sentence. Example:

```
# BAD — wall paragraph (unreadable):
[EVIDENCE: summary.json] hard/roll ss_error=1.10 CV=2.65, hard/pitch ss_error=0.35
CV=1.87, none/roll ss_error=0.55 CV=0.84, soft/roll ss_error=0.30 CV=1.12

# GOOD — bullet list:
[EVIDENCE: summary.json hard/roll, soft/roll, none/roll]
- none:  roll ss_error=0.55, CV=0.84
- soft:  roll ss_error=0.30, CV=1.12
- hard:  roll ss_error=1.10, CV=2.65 (heavy-tail: some envs dominate)

# GOOD — table for multi-axis × multi-DR:
[EVIDENCE: summary.json]
| dr_level | roll ss_error | pitch ss_error | roll CV |
|----------|--------------|----------------|---------|
| none     | 0.55         | 0.15           | 0.84    |
| soft     | 0.30         | 0.13           | 1.12    |
| hard     | 1.10         | 0.35           | 2.65    |
```

## Before drafting — the groups ARE the required table of contents (PRE-WRITE gate)

Completeness is decided BEFORE a single sentence is written, not audited after.
The dr-harder report failed THREE times the same way: the agent drafted what
"looked important" by feel, then checked coverage afterward and found whole
diagnostic groups missing. The `metrics.yaml` `groups` field exists to prevent
exactly this — treat it as the report's required table of contents.

Before drafting `report.md`:

1. **Load the profile's `groups`** (`<root>/.omx/profile/metrics.yaml`, the `groups:`
   mapping — e.g. tracking / reward_decomp / trpo / critic / encoder / constraint /
   doraemon). These ARE the diagnostic families the report must cover.
2. **Create one TodoWrite item PER GROUP** before writing prose. Each becomes a
   report section you will satisfy with a code-exec number (not a hand-waved mention).
   Do NOT pick metrics by feel — the groups are the coverage contract.
3. **The metrics.yaml groups are the report's required table of contents, decided
   before a single sentence is written — not an after-the-fact audit.** A group is
   only droppable if it is genuinely N/A for this run, and only after the
   "Verify the engine's output" cross-check below (an empty engine cell is NOT an
   N/A — dump the raw TB tags first).
4. **Bookend the group sections with a TL;DR (top) and a closing verdict (bottom).**
   The group sections are the *evidence body*; a reader must not have to synthesize it
   themselves. So the report opens with a `## TL;DR` (3–6 bullets: the healthy baseline
   state + the ONE real weakness + the headline metric that exposes it) and CLOSES with a
   `## verdict` / `## bottom line` section that answers, in 2–4 sentences grounded in the
   sections above: what is this run's single most important takeaway, and what does it
   imply for the next experiment. A report that ends on the last diagnostic group (no
   closing synthesis) is incomplete — the per-group findings are inputs to the verdict,
   not a substitute for it. (Symptom this fixes: the dr-harder teacher report had a TL;DR
   but trailed off after the `doraemon` group with no closing synthesis.)

This PRE-WRITE checklist is what actually prevents the skip; the `omx report-coverage`
run in "When done" is the backstop that catches a checklist you didn't honor.

## Building the report (permanent tree, via the core — never hand-write paths)

> **Grouped runs (purpose / experiment_name layer).** When a run lives under an extra
> grouping layer — `<output_root>/<group>/<run_id>/` (e.g. `rsl_rl/albc_trpo_teacher/dr_harder`)
> rather than flat `<output_root>/<run_id>/` — pass that prefix as `--group <group>` to
> `omx promote-plots` AND as the keyword arg `group="<group>"` to every `OmxPaths` getter
> (`report_md` / `report_ko_md` / `manifest_json` / `analysis_dir`), so the report lands
> BESIDE the run instead of in a phantom flat dir. Omit it for flat layouts (the default).
> **MUST: the group must contain ALL path segments between output_root and run_id.** For
> RSL-RL runs the framework subdir is part of the group — pass `rsl_rl/<exp_name>/<purpose>`
> (e.g. `rsl_rl/albc_trpo_teacher/dr_harder`), NOT just `<exp_name>/<purpose>`. Omitting
> the framework segment silently drops the report into a sibling tree
> (`experiments/albc_trpo_teacher/...` instead of `experiments/rsl_rl/albc_trpo_teacher/...`).
> The group string is validated (alnum/_/- per segment, no traversal). The `omx wiki add
> --from-report` path then becomes `<output_root>/<group>/<run_id>/analysis/<analysis_id>/report.md`.

1. Choose an `analysis_id` = `<verb>-<YYYYMMDD-HHMMSS>` (verb = lowercase, e.g. `compare`, `diagnose`; verb FIRST so output names read label-before-date consistently). Get the timestamp from `date +%Y%m%d-%H%M%S` via Bash and prefix the verb: e.g. `diagnose-$(date +%Y%m%d-%H%M%S)`.
2. Resolve `output_root` from the profile's `metrics.yaml`.
3. Draft `report.md` referencing ONLY the plots you actually used (by bare filename, e.g. `![](plots/ss_error__trajectory.png)`).
4. Promote the referenced plots: `omx promote-plots --root <root> --session-id <sid> --output-root <output_root> --run-id <run_id> --analysis-id <analysis_id> --referenced <name> [--referenced <name> ...]`. This moves them from scratch into `analysis/<analysis_id>/plots/`. If it loud-fails on a missing plot, you referenced a plot you never rendered — fix the report or render it. A pure-numbers analysis may reference ZERO plots — that is valid; skip this step if so (atomic_path in the next step will create the analysis dir).
5. Write `report.md` into the permanent tree THROUGH the core's atomic writer so the path comes from the getter AND the analysis dir is created (this also covers the zero-plot case where promote-plots created no dir):

   ```bash
   python3 - <<'PY'
   from omx_core.omx_paths import OmxPaths, atomic_path
   p = OmxPaths(root="<root>").report_md("<output_root>", "<run_id>", "<analysis_id>")
   with atomic_path(p) as tmp:
       tmp.write_text(r"""<the full report.md text you assembled>""")
   print(p)
   PY
   ```
6. Write the Korean mirror `report.ko.md` the same way — author the SAME analysis (same findings, same evidence tags, same numbers — a faithful translation, not a re-analysis) as Korean prose, path from `report_ko_md(...)`, written through `atomic_path`. `report.md` (English) stays canonical: wiki auto-capture and `omx report-parse` read `report.md`, NEVER `report.ko.md`. The Korean file is the human-facing mirror only; both share the same `plots/` and `manifest.json`.

   ```bash
   python3 - <<'PY'
   from omx_core.omx_paths import OmxPaths, atomic_path
   p = OmxPaths(root="<root>").report_ko_md("<output_root>", "<run_id>", "<analysis_id>")
   with atomic_path(p) as tmp:
       tmp.write_text(r"""<the full report.ko.md text — Korean translation of report.md>""")
   print(p)
   PY
   ```
7. Write `manifest.json` next to it, the same way (path from `manifest_json(...)`, write through `atomic_path`):

   ```bash
   python3 - <<'PY'
   import json
   from omx_core.omx_paths import OmxPaths, atomic_path
   p = OmxPaths(root="<root>").manifest_json("<output_root>", "<run_id>", "<analysis_id>")
   manifest = {
       "inputs": [<...resolved result paths...>],
       "profile_hash": "<...>",
       "omx_version": "<...>",
       "git_sha": "<short sha or n/a>",
       "analysis_id": "<analysis_id>",
       "generated_by": "exp-analyze",
   }
   with atomic_path(p) as tmp:
       tmp.write_text(json.dumps(manifest, indent=2))
   print(p)
   PY
   ```
   Get git_sha via `git -C <repo> rev-parse --short HEAD` if in a repo; else `"n/a"`.

## Hard constraints (never violate)

- NEVER launch training or eval (no `launch.sh`, no live eval_dr). Analysis reads existing results only.
- NEVER write a path by hand; every `.omx/`/output path comes from an `omx` verb or `omx_paths` getter, and every permanent-tree write goes through `atomic_path`/`atomic_dir`.
- NEVER claim a number you did not get from code-exec. PNG vision is for SHAPE, not digits.
- Candidate plots that the report doesn't reference are LEFT in scratch (omx clean sweeps them) — do not delete them yourself.
- Respond to the user in the user's language (the machine's locale language); keep report.md/code/markdown in English.
- **D2 — report.md contains ONLY this run's analysis results.** Harness/engine-gap
  metadata, CLI-misuse notes, and metrics.yaml coverage checks do NOT belong in
  report.md — those go to the wiki engine-gap page + docs/plans fix-prompt. The report
  is an analysis deliverable, not a harness audit log. (Incident: a report included
  "Cross-check ledger / Harness gaps / metrics.yaml note" sections that had to be
  removed manually. The SKILL did not block it — this rule does.)

## Capture reusable findings into the wiki (auto-capture — the write half of the loop)

The report.md is this analysis's full deliverable. The wiki holds the SUBSET worth
reusing across future runs. exp-analyze already QUERIES the wiki before analyzing
(see "Ground in prior workspace knowledge" above); this step closes the WRITE half
so the harness specializes to THIS workspace the more it is used — no explicit
"learn" invocation needed. **Do this automatically at the end of every analysis**
(light channel, no approval needed) unless the user passed `--no-wiki`.

To not miss candidates, let the core extract them first:

`omx wiki add --root <root> --from-report "<output_root>/<run_id>/analysis/<analysis_id>/report.md"`

This prints `{"candidates": [...]}` and writes NOTHING. Choose the durable, reusable
ones (not run-specific noise), then write each chosen page (you decide
title/category/tags - the core does not):

`omx wiki add --root <root> --title "<short reusable title>" --category <pattern|debugging|decision|reference> --confidence <high|medium|low> --tags "<axis>,<symptom>" --sources "<analysis_id>" --content "<the finding, with its evidence>"`

Auto-capture discipline (append-only, non-destructive, frictionless):
- **Automatic, not gated.** Append at analysis end without asking; `omx wiki add`
  merges (append-only, never overwrites — same slug unions tags/sources, keeps the
  higher confidence). Honor `--no-wiki` to skip entirely.
- **Dedupe before writing.** If the same finding already lives in a page, the merge
  appends a dated update rather than a duplicate — that is fine; do not hand-create a
  second page for the same topic.
- **Nothing to record is a valid outcome.** An analysis that surfaced only
  run-specific noise writes ZERO pages. Skip silently — a wiki full of every run's
  noise stops being useful.

### Write the CONCLUSION *and* its evidence — never a bare label (re-read-cost rule)

A wiki note must carry the load-bearing evidence that backs its claim, not just the
label. A label-only note forces the next session to re-open the source to find out
*why* — that re-read cost is the classic learning failure. Co-locate, in the same note:
- the conclusion (one line),
- the supporting evidence — concrete numbers WITH their code-exec source (the command
  or `file:field` that produced them), and an internal navigation pointer
  (`analysis_id` / report section to re-visit), NOT a bare metric name.

"roll regresses under hard DR" is a label. "roll ss_error 0.31→0.76 from soft→hard DR
(summary.json hard/roll/ss_error; analysis `<analysis_id>` §heavy-tail) — CV 1.4 so a
few envs dominate" is reusable knowledge. This mirrors the skill's own hard constraint
(a numeric claim must trace to a code-exec source, never a PNG) — carry that trace INTO
the wiki note. This is a *recommendation*, not a gate: the light channel's value is being
cheap and frictionless, so missing evidence does not block the write — it just makes the
note weaker.

### Which category — what each holds in an experiment workspace

The 8 categories are domain-neutral; for run analysis, lean on these four and mean
something specific by each:
- `pattern` — a recurring metric BEHAVIOUR (e.g. "entropy collapses when noise_std
  floors"). The *shape* a run takes.
- `debugging` — a diagnostic PROCEDURE that worked ("to tell heavy-tail from
  sample-mean divergence, run per-env CV then axis rho").
- `decision` — why something was adopted or discarded, with the data that decided it.
- `reference` — a stable threshold / formula / fact (e.g. an axis acceptance bound).

Lean toward `pattern`/`decision`/`reference` for facts that recur across runs; reserve
`debugging` for reusable how-to. Do not over-record working preferences as findings.

## Record engine-gap specs — the analysis ENGINE specializes too (not just knowledge)

The wiki captures more than findings ABOUT runs; it also captures how this workspace's
analysis ENGINE should grow. The "engine" is ALL the ANALYSIS code this workspace owns —
code that READS results without changing them. Two homes:
- the reference adapter the profile points at (`.omx/profile/` — e.g. a TB/wandb diagnostic
  script), and
- the workspace's own pure post-processing source (e.g. a `analysis/` package that reads
  saved `*.npz`/`summary.json` and computes heavy-tail / divergence / comparison stats).
Both are fair game to specialize. The dividing line is NOT where the file lives — it is
whether the code READS experiment results or PRODUCES them. Analysis/post-processing code
(reads results) may be grown; experiment-determining source (model / reward / training /
env — code whose change would alter the results themselves) is OFF LIMITS here (that is
what the next experiment's probe proposes, never an analysis-time edit).

When, during analysis, you hit a limit of that engine — a metric pattern it does not
diagnose, a plot it cannot render, a threshold it hardcodes wrong for this workspace, a
post-processing stat the `analysis/` package is missing, or the user says "the analyzer
should also check X" — **record that as an engine-gap spec in the wiki** (`category=decision`),
so the next session can act on it instead of re-discovering the same gap.

An engine-gap spec is a CODE-CHANGE specification, not a finding. Write it concretely:
- `[ENGINE-GAP]` what the engine cannot currently do (one line).
- `[WHERE]` the analysis file + section to change — either the profile adapter (e.g.
  `.omx/profile/analyze_training.py` DIAGNOSIS block) or the workspace's own post-processing
  source (e.g. `analysis/<module>.py` <function>), and which of the two it is — as best you
  can point. If the capability is genuinely new (no file does it yet), say "new module" and
  name where it should live.
- `[SPEC]` the rule/behaviour to add, precise enough to implement (e.g. "flag mode-switch
  rate > 0.2 as CYCLING").
- `[EVIDENCE]` what in THIS analysis exposed the gap (the run + metric that needed it).
- `[STATUS]` `proposed` (until a later session implements it).

**Engine-gap specs go to the WIKI, NOT to report.md.** An engine-gap spec is
operational metadata about the harness, not a finding about the run — see the
D2 hard constraint above. Write it with `omx wiki add ... --category decision
--tags engine-gap`, never inline in the analysis report body.

Title these pages so they are findable (e.g. "engine-gap: <capability>"), tag `engine-gap`.
This is how "the engine specializes the more the wiki is used" actually closes: analysis
writes the spec → a later session reads it (see exp-design / the implement step) → the
adapter is updated → the spec page is flipped to `[STATUS] implemented`. Do NOT edit the
adapter yourself during analysis (exp-analyze never mutates code) — only record the spec.

## Wiki maintenance (gc)

When the wiki accumulates overlapping or superseded pages, consolidate it — but
the core never decides *what* to remove; you do, and a human approves.

1. `omx wiki gc --root <r>` — read-only. Returns `{lint, pages:[{slug,title,category,updated,bytes}]}`.
2. For each merge/delete candidate, `omx wiki read --slug <slug> --root <r>` to read the
   FULL body. lint catches mechanical signals (orphan/stale/oversized); only reading the
   bodies reveals *semantic* duplicates (two pages that are one topic, a later page that
   supersedes an earlier one).
3. Write a proposal `proposals/<ts>-wiki-gc.md` with `---\nkind: wiki-gc\n---` frontmatter,
   a `## DELETE` section (`- slug: X` + `reason:`), and a `## MERGE` section
   (`- into: X` / `from:` list + `reason:`). Each item carries a one-line reason.
4. STOP. The user reviews the proposal and deletes any line they disagree with —
   editing the file IS the approval. Never apply without this human gate.
5. `omx wiki gc-apply --proposal <file> --root <r>` — two-phase: validates the whole
   proposal (slugs exist, git-tracked, no self-merge) then executes under the wiki lock.
   It REFUSES to touch any page git does not track (so `git restore` always recovers).
   The core executes but does not commit — commit the result yourself after review.

Never hand-delete or hand-merge wiki pages with Edit/Write/rm: that bypasses the lock,
the index regeneration, the append-log, and the git-recovery guard.

## Completeness gate — the backstop (GAP 4); the PRE-WRITE checklist is the real fix

The PRE-WRITE checklist ("Before drafting" above) is what prevents a skipped group.
This lint is the BACKSTOP that catches a checklist you did not honor. Running it
only AFTER writing — with no pre-write checklist — is the failure mode (dr-harder 3x):
it caught nothing because the agent had already convinced itself the report was done.

After writing `report.md`, run the coverage lint so a report that skipped a whole
diagnostic group or never cited the engine cannot pass silently. Run it in STRICT
mode so a group named only once (when it has several metrics) is caught, not just a
group skipped entirely:

`omx report-coverage --path <output_root>/<group?>/<run_id>/analysis/<analysis_id>/report.md --root <root> --min-coverage 0.5`

It reads the profile's optional `groups` (diagnostic-group → metrics) and
`engine_markers`, prints per-group `group_hits` (hit/total — so you see WHERE it is
thin), and **loud-fails (non-zero exit)** if any declared diagnostic group is under-
covered, or if no engine marker is cited (the report looks hand-extracted rather
than engine-grounded). Without `--min-coverage` the lint is lenient (a group passes
on a single referenced metric) — that lenient default is for back-compat, but for a
real analysis use `--min-coverage 0.5` so shallow partial coverage fails. On failure:
either fill the under-covered group with code-exec numbers / run the engine and cite
its output, OR — if a group is genuinely N/A for this run — state that explicitly in
the report, then re-run the lint. Do not mark the report done while the lint fails
without a stated reason. (If the profile declares neither `groups` nor
`engine_markers` the lint is a vacuous pass — that is fine for a fresh workspace;
consider proposing the fields as an engine-gap spec.)

A group is allowed to be "N/A for this run" ONLY after the cross-check above:
"the engine reported it empty" is NOT a valid reason to skip a group. If the
engine printed `0`/empty for that group, you must first dump the raw TB tags
(see "Verify the engine's output") — if the tags exist, the group is NOT N/A
(extract it via `omx reduce tb-final` and cite it); only genuinely-absent tags
justify the N/A. This closes the loop: the gate catches a skipped group, and the
cross-check rule stops "the engine said 0" from being used to wave the skip through.

## When done

Tell the user where the report is (`<output_root>/<run_id>/analysis/<analysis_id>/report.md`),
summarize the top findings (with their confidence), and **prove the completeness gate
passed before declaring done** — show that `omx report-coverage ... --min-coverage 0.5`
returned `ok: true` (or state the explicit, cross-checked N/A exceptions for any group
it flagged). A report whose strict coverage lint fails is NOT done: fill the thin group
and re-run. Also confirm the report is **bookended** — a `## TL;DR` at the top and a
closing `## verdict` / `## bottom line` at the bottom (PRE-WRITE step 4); a report that
ends on its last diagnostic group with no closing synthesis is not done. The PRE-WRITE
per-group TodoWrite checklist ("Before drafting") is what should have prevented any
failure here; this final lint is the backstop. Then STOP.
Do not propose or launch a next experiment — that is exp-design's job (#5).
