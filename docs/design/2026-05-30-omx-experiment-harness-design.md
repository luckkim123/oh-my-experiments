# OMX (oh-my-experiments) — Self-Contained Experiment-Analysis Harness Design

> Status: DESIGN DRAFT (pre-implementation). Author session: 2026-05-30.
> Scope: a standalone, deployable Claude Code plugin for (a) analyzing many RL/research
> experiment results and (b) designing the next experiment. OMC was reverse-engineered only
> as a *reference* for how to build a harness — OMX has **zero runtime dependency** on OMC.

---

## 0. Decisions locked in this session (do not re-litigate)

| # | Decision | Rationale (from this session) |
|:--|:--|:--|
| D1 | **Self-contained**, not an OMC extension | OMC studied as a pattern reference, not a dependency. Avoids version-coupling. |
| D2 | **Python core** (`omx-core`), framework-agnostic | User's ecosystem is Python; analysis logic is Python; runs without Claude for testing. OMC being TypeScript is their choice, not a constraint. |
| D3 | **(B) Lightweight runtime: skills + `omx` CLI + `.omx/` JSON state.** No custom MCP server. | Dependency surface = "Bash runs Python" + "file IO" — the most version-resilient interface. Persistent-kernel benefit is small (1 run = 1 load). (B)→(A) MCP promotion is easy later if needed. |
| D4 | **Semi-autonomous + "leaving-work" toggle** | Default: analyze + design + define-evaluator autonomously, **human-approves the actual training launch** (repo rule: "훈련 종료/시작은 유저가 직접"). One session flag flips to fully unattended (autoresearch-style max-runtime ceiling). |
| D5 | **Score formula / metric-truth-source = a USER-PROFILE slot, not a core constant** | User said "잘 모르겠다" about mean+CV vs per-axis worst-case — correctly, because it is experiment-specific. The `exp-init` interview elicits it per user. |
| D6 | **omha integration = 1st-class LANE card** (`cards/omx.json`), same level as OMC/superpowers — NOT a 2nd-tier domain handler like oms/omd | OMX is a *way of working* (analyze→design→loop), not an output domain (slides/docs). Verified: omha `cards/` holds only `omc.json` + `superpowers.json`; oms/omd live in the 2nd-tier cascade. OMX belongs at tier-1. |
| D7 | **claudebase installs OMX alongside OMC/SP**, with OMC version-pinned | Single source of truth; intentional upgrades only. |
| D8 | **Directory/naming discipline is a first-class core feature** (§10): permanent-output root = chosen by `exp-init` (profile slot); `.omx/` intermediates = 2-axis (run-id cache + session-id scratch); cleanup = review-gated ritual, never auto-delete | User is "광적으로 집착" about structure. A path-enforcement single-source-of-truth module + a fixed (never-ad-hoc) `.omx/` schema + a dry-run→diff→approve cleanup. Mirrors repo `paths.py` single-truth and `model-trim-disaster` lesson. |

---

## 1. What OMX borrows from OMC (patterns, re-implemented — never imported)

Verified against `/root/.claude/plugins/marketplaces/omc/` source this session:

| OMC pattern | Source (verified) | OMX re-implementation |
|:--|:--|:--|
| **Evaluator contract** `{pass: bool, score?: number}`, loud-fail on bad JSON | `src/autoresearch/contracts.ts` (`parseEvaluatorResult`) | `omx-core` evaluator runner: parse user evaluator stdout's last line as JSON, throw on missing `pass` / non-numeric `score`. |
| **keep-policy + auto-revert** (`score_improvement`, `git reset --hard last_kept`) | `src/autoresearch/runtime.ts` (`decideAutoresearchOutcome`, `appendDecisionLog`) | `omx loop` keep/discard gate. Wraps repo "minimum-change revert" rule. |
| **Decision-log 3-artifact** (`results.tsv` + `ledger.json` + `decision-log.md`) | `runtime.ts` | `.omx/runs/<id>/` writes the same trio → satisfies `/workspace/docs/results/<id>.md` YAML front-matter convention. |
| **Ambiguity-gated Socratic interview** (weighted dimension scoring, threshold gate, `pending approval` artifact) | `skills/deep-interview/SKILL.md` | `exp-init` skill: same gate, but with an **experiment-domain question topology** (objective / metrics / eval-method / success-criteria / launch-recipe). |
| **Evidence tags** `[FINDING]/[EVIDENCE:file:lines]/[CONFIDENCE:HIGH|MED|LOW]` | `skills/sciomc/SKILL.md` | OMX analysis output schema — enforces repo "추측 금지, 코드/데이터로 증명" rule structurally. |
| **Evidence-strength hierarchy + discriminating-probe** (controlled repro > primary artifact > inference > speculation; probe = next experiment) | `skills/trace/SKILL.md` | `exp-design` skill: 3-lane diagnosis (code-path / config-DR-hyperparam / measurement-artifact) → the discriminating probe IS the proposed next experiment. |
| **Sealed-evaluator** (validate.sh prevents evaluator self-modification) | `skills/self-improve/scripts/validate.sh` | `omx loop` seals the user's evaluator script before each iteration (no self-grading). |
| **cross-session memory** (notepad/wiki/state/session_search MCP) | `src/tools/*-tools.ts` | OMX uses `.omx/` files + a grep-able registry (no MCP); keyword index like wiki, no embeddings. |

**Key point:** none of the above is an `import`. OMX reads its own `.omx/` namespace, never `.omc/`. If OMC changes any version, OMX does not notice.

---

## 2. Version-resilience analysis (answers "OMC 업데이트되면 호환성 틀어지지 않나?")

Three coupling points, ranked by fragility:

| Coupling point | OMC update impact | Mitigation |
|:--|:--|:--|
| OMX core (analyze/loop/plot) | **Zero** — no OMC import/call | Immune by construction (D1/D2). |
| Shared dir (`.omc/` vs `.omx/`) | **Zero** — separate namespace | Immune by namespace split. |
| Runtime interface | (B) uses only Bash+fileIO, the most stable CC interface; (A) MCP would couple to MCP spec | **(B) chosen (D3)** → minimal surface. |
| **omha router** (the only real risk) | OMC skill renames / card-format change could mis-route | (i) OMX card uses **keyword+intent only**, never references OMC skill names; (ii) OMX skills self-register trigger keywords in their own `plugin.json`/descriptions (dual discovery); (iii) claudebase **pins OMC version**. |

Conclusion: the only thing that *can* break is routing (not OMX function), and the omha `cards/*.json` design (registry.py line 1-2: "adding a harness = drop one JSON file, core never changes") makes the OMX card fully decoupled from OMC internals.

---

## 3. Architecture — two layers

```
┌─ GENERIC CORE (deployed, domain-agnostic) ──────────────────────────────┐
│  omx-core (pure Python pkg)        + OMX skills (Claude CC)              │
│  · ingest adapters: WandB / TB / CSV / JSON / eval-summary               │
│  · reduce: summary-stat-first · downsample · plot-PNG generation         │
│  · analyze: PNG-vision + code-exec hybrid router (§5 branch rules)       │
│  · loop: propose→eval(contract)→keep/discard→log  (autoresearch shape)   │
│  · state/memory: .omx/ JSON + grep-able result registry                  │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │  ← user fills these slots (exp-init interview)
┌──────────────────────────────┴──────────────────────────────────────────┐
│  USER PROFILE (per-researcher, NOT deployed) — written to .omx/profile/  │
│  · evaluator.sh  — my eval command + score formula (D5 lives here)       │
│  · metrics.yaml  — my metric names / axes / thresholds                   │
│  · rules.md      — my analysis discipline ("CV mandatory", etc.)         │
│  · launch.sh     — my training command + GPU gate                        │
└──────────────────────────────────────────────────────────────────────────┘
```

The user's Isaac Lab / eval_dr setup = the **first reference profile** (dogfood). It is NOT baked into core.

---

## 4. The 4 OMX skills (+ `omx` CLI underneath)

| Skill | Role | Borrows | Output |
|:--|:--|:--|:--|
| **`exp-init`** | Bootstrap (the "research /init"). Socratic interview → writes user profile. | deep-interview ambiguity gate + experiment-domain topology | `.omx/profile/{evaluator.sh, metrics.yaml, rules.md, launch.sh}` marked `pending approval` |
| **`exp-analyze`** | Runtime analysis of N runs. Reads profile, runs hybrid PNG-vision + code-exec. | sciomc fan-out + evidence tags; `train-analyze` generalized to a reference adapter | `.omx/runs/<id>/analysis.md` + PNG paths + evidence-tagged findings |
| **`exp-design`** | Propose the next experiment from analysis. | trace 3-lane → discriminating-probe | `.omx/proposals/<id>.md` (the probe = next config), `pending approval` |
| **`exp-loop`** | Semi-autonomous: propose→eval→keep/discard→log→repeat. "Leaving-work" toggle for unattended. | autoresearch evaluator-contract loop + keep-policy + max-runtime ceiling | `.omx/runs/<id>/{results.tsv, ledger.json, decision-log.md}` |

`omx` CLI (pure Python, Claude-free): `omx ingest`, `omx reduce`, `omx analyze`, `omx eval`, `omx loop` — each callable standalone via Bash. Skills are thin Claude wrappers that orchestrate these + read the PNGs back via vision.

---

## 5. Analysis branch rules (the hybrid router — core IP)

Verified token economics this session (Anthropic docs; **model-dependent** — corrected for Opus 4.8):
- Raw CSV/table ≈ cells × 1–3 tok → eval matrix = many k tokens; LLM unreliable at long-number arithmetic.
- Plot-PNG (vision) = `width×height/750`. **Opus 4.8: cap 2576px, up to ~4,784 tok/img** (older models: 1568px, ≤~1,568 tok). Still a 1–2 order-of-magnitude win for large data — but keep plots ≤2576px (bigger just downscales + wastes tokens; prefer several ~1500px plots over one huge one).
- Code-exec (REPL) = code string + summarized output only; exact arithmetic done by code.

| Question type | Winner | Why |
|:--|:--|:--|
| shape / convergence point / divergence span / heavy-tail tail | **PNG-vision** | one curve compresses thousands of points |
| exact numbers: mean, CV=std/mean, per-axis max, slope | **code-exec** | LLM can't do long-number arithmetic; `groupby().agg()` is exact |
| where two runs diverged (aligned multi-series) | **PNG overlay** OR **code stride-extract** | visual point = PNG, exact iter = code |
| one-line verdict (pass/score) | **code-exec → JSON scalar** | evaluator gate's single truth; PNG is non-deterministic |

Pipeline: **summary-stat-first → PNG if shape question → code-exec for precise verification.** Never put raw CSV in context.

---

## 6. omha lane card (`cards/omx.json`) — schema verified against `cards/omc.json`

Drop-in 1st-tier lane. Registered automatically by **both** channels: pull (`route_emit.py` UserPromptSubmit) and push (`cross_lane_emit.py` PreToolUse — matches Write/Edit extensions + Skill names). Draft:

```jsonc
{
  "name": "oh-my-experiments",
  "description": "Experiment-analysis & design lane. Route here when the work is about ANALYZING experiment/training RESULTS or DESIGNING THE NEXT EXPERIMENT: compare runs, read eval/training curves, diagnose why a run regressed, propose the next config, run a semi-autonomous analyze→design→eval loop. Governs HOW you work on experiments — NOT writing the model code itself (that is superpowers), NOT generic parallel throughput (that is oh-my-claudecode).",
  "url": "http://localhost:8973/omx",
  "version": "0.1.0",
  "capabilities": {},
  "default_input_modes": ["text/plain"],
  "default_output_modes": ["text/plain"],
  "skills": [
    {"id": "experiment-analysis", "name": "experiment-analysis-lane",
     "description": "Signals that route to oh-my-experiments (session then picks exp-init/analyze/design/loop).",
     "tags": ["experiment", "analysis", "eval", "run-comparison", "next-experiment",
              "training-curve", "regression", "실험", "분석", "평가", "런비교", "다음실험"],
     "examples": [
       "analyze these N training runs and tell me what changed",
       "이 run들 분석하고 다음 실험 설계해줘",
       "why did this run regress vs baseline — diagnose from the curves",
       "eval 돌리고 plot 보여줘",
       "compare run A and run B at the same iteration",
       "set up the experiment-analysis infra for this research (exp-init)",
       "퇴근할 거니까 알아서 분석하고 다음 실험까지 돌려놔"
     ]}
  ],
  "triggers": {
    "extensions": [],
    "skills": ["exp-init", "exp-analyze", "exp-design", "exp-loop"]
  }
}
```

**Version-resilience:** description/tags/examples reference only experiment intent + OMX's own skill names — zero OMC internals. Safe across OMC upgrades.

---

## 7. claudebase installer entry

Alongside oms/omd/omc/superpowers: add OMX marketplace + install step; **pin OMC to a known version/commit** so upgrades are intentional. On any OMC bump, re-check `cards/omx.json` still doesn't collide (it won't, by §6).

---

## 8. Build order (proposed — for the next planning pass)

0. **`omx_paths.py` — the path single-source-of-truth FIRST** (§10). Every id regex, every `.omx/` + output-tree getter, loud-fail validation, mandatory `session_id` for scratch. Everything else imports paths only from here. Build + test this before any artifact-writing code exists, so no module can ever hand-roll a path. **Pure-Python, fully unit-testable Claude-free.**
1. `omx-core` skeleton: ingest adapters + reduce (summary-stat/downsample/plot) + evaluator-contract runner + `.omx/` state schema (all paths via §0 module). **Test Claude-free via `omx` CLI.**
2. RL-robust evaluator wrapper (the §0-D5 slot) — reference profile for Isaac Lab/eval_dr. Deterministic `{pass,score}`, robust aggregate (mean+λ·CV or per-axis worst — chosen in `exp-init`).
3. `exp-analyze` skill (hybrid router §5) — the most-used path; validate on real eval_dr runs.
4. `exp-init` skill (interview topology) — bootstraps the profile.
5. `exp-design` skill (trace 3-lane → probe).
6. `exp-loop` skill (autoresearch loop + leaving-work toggle + 1-GPU serialization + nvidia-smi gate).
7. `cards/omx.json` + omha registration + claudebase installer entry + OMC version pin.

---

## 10. Directory & naming discipline (core feature — D8)

Three principles, each enforced by code (not by agent goodwill):

1. **Physical split: user-output vs agent-intermediate.** Like git tracked/untracked. Permanent, human-facing artifacts (analysis reports, plots, next-experiment proposals) live in a clean run-id tree. One-shot agent scratch (temp plots, parse caches, scratch scripts) is quarantined under `.omx/`.
2. **`.omx/` itself has a FIXED schema** — not "it's temp so whatever." Intermediates only ever land in pre-declared slots; the structure never varies run-to-run. Enforced by a single path module (`omx_paths.py`) so an agent physically cannot write "somewhere random". Mirrors repo `paths.py:135/262` single-truth rule.
3. **Cleanup is a review-gated ritual** — never auto-delete. On "work complete" judgment or explicit user request: classify → dry-run → show diff → get approval → move to trash (never `rm`). Mirrors repo `model-trim-disaster` lesson (numeric sort, dry-run mandatory).

### 10.1 Permanent output tree — root chosen by `exp-init`, layout fixed by core

`exp-init` writes `output_root` into `.omx/profile/metrics.yaml`. The **layout under that root is core-fixed** (the user picks only *where the root is*, never *how it's shaped* — that's the discipline). Default root = repo `experiments/` (matches existing eval_dr convention); profile may override.

```
<output_root>/<run_id>/                 # run_id = the experiment's canonical id (profile-defined format)
├── analysis/
│   └── <analysis_id>/                  # analysis_id = <YYYYMMDD-HHMMSS>-<verb>  e.g. 20260530-143022-compare
│       ├── report.md                   # the human deliverable (evidence-tagged findings)
│       ├── plots/                      # PNGs the user is meant to see
│       │   └── <metric>__<view>.png    # e.g. attitude__trajectory.png, ss_error__per_axis_bar.png
│       ├── tables/                     # exact-number CSVs the user may want (code-exec outputs)
│       │   └── <metric>__<agg>.csv     # e.g. ss_error__by_axis.csv
│       └── manifest.json               # what was analyzed (inputs, profile hash, omx version, git sha)
├── proposals/
│   └── <proposal_id>.md                # proposal_id = <YYYYMMDD-HHMMSS>-next  (the discriminating probe = next config)
└── eval/                               # (untouched — user's existing eval_dr output convention)
```

Naming rules (regex-enforced in `omx_paths.py`):
- `analysis_id` / `proposal_id` timestamp = `\d{8}-\d{6}` (sortable, no ambiguity, **numeric sort = chrono sort**).
- artifact filename = `<metric>__<view>.<ext>` — double-underscore separates semantic fields; **never** spaces, never run-to-run-variable names. `metric`/`view` drawn from a closed vocabulary in `metrics.yaml`.
- one analysis = one `<analysis_id>/` dir, atomic (write to `.tmp` sibling, `os.replace` on success) — partial analyses never pollute the clean tree.

### 10.2 `.omx/` intermediate tree — FIXED schema, 2-axis lifecycle (D8 / Q2-c)

```
.omx/
├── profile/                            # PERMANENT — the user's tuning (survives all cleanup)
│   ├── evaluator.sh                    # eval command + score formula (D5 slot)
│   ├── metrics.yaml                    # output_root, metric/view vocab, axes, thresholds
│   ├── rules.md                        # user's analysis discipline ("CV mandatory", ...)
│   └── launch.sh                       # training command + GPU gate
├── runs/                               # AXIS 1: run-bound — persists across sessions, cleaned per-run
│   └── <run_id>/
│       ├── results.tsv                 # autoresearch terse rows (1 iter = 1 row)
│       ├── ledger.json                 # full structured iteration ledger
│       ├── decision-log.md             # prose decision blocks
│       └── cache/                      # parsed metric frames, downsample caches (re-derivable)
│           └── <source>__<metric>.parquet
├── scratch/                            # AXIS 2: session-bound — volatile, safe to wipe anytime
│   └── <session_id>/                   # = OMC's .omc/state/sessions/{sessionId} pattern (concurrent-safe)
│       ├── plots/                      # throwaway PNGs the agent looked at but user won't keep
│       ├── py/                         # scratch analysis scripts the agent generated
│       └── notes.md                    # agent working notes for THIS session only
├── registry/                          # PERMANENT — grep-able discovery index
│   ├── INDEX.md                        # one line per analysis/proposal (id · type · date · summary · path)
│   └── findings/                       # wiki-style keyword+tag findings store (no embeddings)
│       └── <slug>.md
└── state.json                          # OMX mode state (active loop?, current_phase, session_id) — single file
```

**Lifecycle separation (why 2-axis):** the repo already runs concurrent multi-GPU sessions (`concurrent-session-albc-marinelab` memory). `runs/<run_id>/cache/` is run-bound (two sessions analyzing the same run share it safely — read-mostly, content-addressed by `<source>__<metric>`). `scratch/<session_id>/` is session-bound (each session's throwaway is isolated — concurrent sessions never clobber each other's scratch).

**Path enforcement (`omx_paths.py` — single source of truth):**
- the ONLY way to get any `.omx/` or output path. No string-concatenation of paths anywhere else in the codebase (lint rule / review gate).
- every getter validates the id against its regex before returning; bad id → raise (loud-fail, never silent-fallback — repo's silent-eval-path-fallback accident lesson).
- `session_id` is **mandatory** for any `scratch/` path (prevents cross-session leak — same defense OMC's `state_write(session_id=...)` uses).

### 10.3 Cleanup ritual (`omx clean` — review-gated, never auto-delete)

Trigger: agent judges "work complete" OR user says "정리해줘". Never fires on its own without surfacing.

```
omx clean [--scope session|run|all] [--apply]
```

1. **Classify** every `.omx/` path into: KEEP (profile/, registry/, runs/*/{results.tsv,ledger.json,decision-log.md}) vs SWEEP (scratch/<sid>/, runs/*/cache/, orphaned .tmp).
2. **Dry-run by default** — prints a tree diff: what moves to trash, what stays, byte counts. No `--apply` = nothing touched.
3. **Show + ask.** Present the diff to the user, require explicit approval (this is the "검토/허락" gate — non-negotiable).
4. **Trash, not rm.** Approved sweep → move to `.omx/.trash/<YYYYMMDD-HHMMSS>/` (recoverable), or env trash (`gio trash`/`trash-cli`) if available. Permanent erase only on a second explicit "this is permanent" confirm. Repo Deletion-Safety rule.
5. **Registry survives.** `registry/INDEX.md` + `findings/` are KEEP always — the discovery trail outlives the scratch.

**Invariants the cleanup guarantees:**
- profile is never swept (user tuning is sacred).
- the permanent output tree (§10.1, outside `.omx/`) is **never touched by `omx clean`** — cleanup only ever operates inside `.omx/`.
- numeric-sortable ids mean a "keep last N analyses" policy is unambiguous (no alphabetical-sort disaster).

---

## 9. Open items deferred to the user / next pass (NOT blocking this draft)

- **Score formula** (mean+λ·CV vs per-axis worst-case, λ, DR-level weighting) — deliberately deferred; `exp-init` elicits it per-profile using past-run data (D5).
- **Deployment packaging** — marketplace repo name, whether `omx-core` ships on PyPI vs vendored in the plugin.
- **1-GPU vs tournament** parallelism in `exp-loop` — autoresearch sequential by default; self-improve tournament only if multi-GPU later.
```
```

> Reference paths (verified this session): OMC patterns — `marketplaces/omc/{src/autoresearch/{contracts,runtime}.ts, skills/{deep-interview,sciomc,trace,self-improve}/SKILL.md, src/tools/*-tools.ts}`. omha — `marketplaces/heroacademia/{src/omha/registry.py, hooks/{route_emit,cross_lane_emit}.py, cards/{omc,superpowers}.json}`. Token economics — Anthropic pricing/vision docs (Opus 4.8: 2576px / ~4784 tok cap).
