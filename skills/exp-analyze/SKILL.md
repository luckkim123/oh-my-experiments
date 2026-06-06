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

## Ground in prior workspace knowledge (query the wiki first)

Before analyzing, pull any accumulated knowledge about this run's topic so you do
not re-derive what the workspace already learned:

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
code-exec output, never to eyeballing a PNG (repo rule: 추측 금지, 코드/데이터로 증명).

## Evidence tags (mandatory in report.md — design §1, sciomc pattern)

Every finding is tagged:
- `[FINDING]` — the claim, one line.
- `[EVIDENCE: <source>]` — the file/command that proves it (e.g. `summary.json hard/roll/ss_error=0.76`, or `Reward/total curve, scratch plot`).
- `[CONFIDENCE: HIGH|MED|LOW]` — HIGH = exact code-exec number or a clear PNG shape; MED = inference across sources; LOW = speculation (avoid — prefer to gather more evidence).

A finding with a numeric claim and `[CONFIDENCE: HIGH]` MUST cite a code-exec source, not a PNG.

## Building the report (permanent tree, via the core — never hand-write paths)

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
- Respond to the user in Korean (repo rule); keep report.md/code/markdown in English.

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

Title these pages so they are findable (e.g. "engine-gap: <capability>"), tag `engine-gap`.
This is how "the engine specializes the more the wiki is used" actually closes: analysis
writes the spec → a later session reads it (see exp-design / the implement step) → the
adapter is updated → the spec page is flipped to `[STATUS] implemented`. Do NOT edit the
adapter yourself during analysis (exp-analyze never mutates code) — only record the spec.

## When done

Tell the user where the report is (`<output_root>/<run_id>/analysis/<analysis_id>/report.md`),
summarize the top findings (with their confidence), and STOP. Do not propose or
launch a next experiment — that is exp-design's job (#5).
