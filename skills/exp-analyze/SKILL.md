---
name: exp-analyze
description: Analyze N existing experiment/training runs into an evidence-tagged report. Use when comparing runs, reading eval/training curves, or diagnosing why a run regressed — the hybrid router decides per question whether to use exact code-exec stats, a vision-read PNG curve, or both. Reads the OMX profile (metrics.yaml) for the metric vocabulary. Writes report.md + promoted plots into the permanent analysis tree. Never launches training or eval. Triggers on "analyze these runs", "compare run A and B", "why did this regress", "런 분석", "eval plot 보여줘".
argument-hint: "[--root <dir>] <run ids or result paths to analyze>"
---

# exp-analyze — hybrid PNG-vision + code-exec run analysis

## Overview

`exp-analyze` analyzes results that ALREADY EXIST. It never launches training or
eval (design D4/B8). It reads the OMX profile written by exp-init, then runs the
hybrid router (design §5) to answer each analysis question with the cheapest
sufficient evidence, and writes a single human deliverable: `report.md` (+ the
plots it references) in the permanent analysis tree.

**Announce at start:** "Using exp-analyze to analyze the runs and write an evidence-tagged report."

## Preconditions (check, don't assume)

1. A profile exists and is approved. Read `<root>/.omx/profile/metrics.yaml`. If it
   is missing → tell the user to run exp-init first; STOP. If `pending_approval: true`
   is still set → tell the user to approve it first; STOP. (Honors the exp-init hard gate.)
2. The runs to analyze exist on disk. The user names run ids or result paths
   (eval_dr summary.json, TB event files, wandb run dirs, data_*.npz). Resolve them;
   if a path is missing, say so and STOP — never fabricate data.

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

1. Choose an `analysis_id` = `<YYYYMMDD-HHMMSS>-<verb>` (verb = lowercase, e.g. `compare`, `diagnose`). Get the timestamp from `date +%Y%m%d-%H%M%S` via Bash.
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
6. Write `manifest.json` next to it, the same way (path from `manifest_json(...)`, write through `atomic_path`):

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

## When done

Tell the user where the report is (`<output_root>/<run_id>/analysis/<analysis_id>/report.md`),
summarize the top findings (with their confidence), and STOP. Do not propose or
launch a next experiment — that is exp-design's job (#5).
