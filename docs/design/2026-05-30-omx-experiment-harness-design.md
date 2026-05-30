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
| D3 | **(B) Lightweight runtime: skills + `omx` CLI + `.omx/` JSON state.** No custom MCP server (neither self-built nor OMC-shared — see §11). | Dependency surface = "Bash runs Python" + "file IO" — the most version-resilient interface. Persistent-kernel benefit is small (1 run = 1 load); exact-arithmetic + plotting are met by the `omx` CLI shelling to `python` and by disk-persistent `.omx/runs/<id>/cache/*.parquet` (more robust than kernel memory: concurrent-safe, survives restarts). The card `url` is **declarative omha-registry metadata, not a live endpoint** (matches `omc.json`/`superpowers.json` — nothing listens on 8973). (B)→(A) **self-built** MCP promotion stays open if OMX ever becomes interactive-iterative; **shared** OMC MCP is permanently rejected (would violate D1). |
| D4 | **Semi-autonomous, but training-launch is NEVER auto-fired** (resolves review B8) | The "leaving-work" toggle governs only the **analyze + design + define-evaluator** phases (autoresearch-style max-runtime ceiling on *analysis*). It **does NOT auto-launch training** — exp-loop *queues* the next launch as a `pending approval` artifact for the human. This honors the CRITICAL repo rule "훈련 종료/시작은 유저가 직접" (`01-critical-behavior.md` Settled / `feedback_training_control`) with no override path. (An explicit, separately-logged user authorization could later de-escalate this, but it is OUT of scope for v0.1 and tracked in §9.) |
| D5 | **Score formula / metric-truth-source = a USER-PROFILE slot, not a core constant** | User said "잘 모르겠다" about mean+CV vs per-axis worst-case — correctly, because it is experiment-specific. The `exp-init` interview elicits it per user. |
| D6 | **omha integration = 1st-class LANE card** (`cards/omx.json`), same level as OMC/superpowers — NOT a 2nd-tier domain handler like oms/omd | OMX is a *way of working* (analyze→design→loop), not an output domain (slides/docs). Verified: omha `cards/` holds only `omc.json` + `superpowers.json`; oms/omd live in the 2nd-tier cascade. OMX belongs at tier-1. |
| D7 | **claudebase installs OMX alongside OMC/SP**, with OMC version-pinned | Single source of truth; intentional upgrades only. |
| D8 | **Directory/naming discipline is a first-class core feature** (§10): permanent-output root = chosen by `exp-init` (profile slot); `.omx/` intermediates = 2-axis (run-id cache + session-id scratch); cleanup = review-gated ritual, never auto-delete | User is "광적으로 집착" about structure. A path-enforcement single-source-of-truth module + a fixed (never-ad-hoc) `.omx/` schema + a dry-run→diff→approve cleanup. Mirrors repo `paths.py` single-truth and `model-trim-disaster` lesson. |

---

## 0.1 Review resolutions (2026-05-30 ground-truth review against OMC 4.14.4 source)

A 5-dimension review verified the doc against actual OMC/omha source (`contracts.ts`, `runtime.ts`, `registry.py`, `omc.json`, `deep-interview/SKILL.md`). Verdicts: card-schema **SOUND**, D5↔#2 **MINOR**, omx_paths **BLOCKING**, exp-init gate **MAJOR**, coherence **BLOCKING**. The blockers below are resolved here; the rest of the doc (§4/§6/§8/§10/§11) is amended to match.

| # | Issue (evidence) | Resolution (locked) |
|:--|:--|:--|
| **B1** | `omx_paths.py` is "#0, pure/Claude-free, unit-testable" (§8) yet must validate `metric`/`view` against `metrics.yaml` and `run_id` against a profile-defined regex (§10.1/§10.2) — mutually exclusive. | **2-tier validation.** (a) *Structural* tier in `omx_paths.py`, profile-free: fixed regexes `analysis_id`/`proposal_id`=`\d{8}-\d{6}-<verb>`, `session_id`, generic `run_id`=`[A-Za-z0-9][A-Za-z0-9_-]*` (no separators/`..`). (b) *Vocabulary* tier (metric/view ∈ metrics.yaml, run_id ∈ profile regex) = an **optional `Profile` injected into getters**; `Profile=None` ⇒ structural-only. Keeps #0 testable in isolation; loud-fail preserved when a profile is present. |
| **B2** | `session_id` mandatory for `scratch/` but no source for the standalone (OMC-free) CLI. | **OMX-native 3-step precedence:** `--session-id` flag → `OMX_SESSION_ID` env → auto-generate `<YYYYMMDD-HHMMSS>-<pid>`. Drop "OMC sessions pattern" wording (inspiration, not dependency). |
| **B3** | exp-analyze output named/located 3 ways (`.omx/runs/<id>/analysis.md` §4 vs permanent `report.md` §10.1 vs absent from §10.2 tree). | **One home:** human deliverable = `report.md` in the **permanent** tree (§10.1). `.omx/runs/<id>/` holds only `{results.tsv, ledger.json, decision-log.md, cache/}`. Plots: exp-analyze writes candidates to `scratch/<sid>/plots/`, then **promotes** (os.replace) only those referenced in `report.md` into permanent `analysis/<analysis_id>/plots/`. §4 + §10 corrected. |
| **B4** | Build DAG inverted: #2 evaluator-wrapper "tunes per profile" but precedes #4 exp-init which writes the profile. | **Re-order + re-scope.** exp-init → **#3** (before exp-analyze). #2 re-scoped: "evaluator-contract runner + Isaac Lab **reference** profile" — consumes a *committed* reference `evaluator.sh`, not a user-elicited one, so buildable pre-init. §8 amended. |
| **B5** | `score` syntactically optional (`contracts.ts:191-200`) but `score_improvement` keep-policy silently discards score-less candidates (`runtime.ts`). | **Document coupling:** score optional under `pass_only`, **required** under `score_improvement`. Reference evaluator ships `pass_only`. §4 annotated. |
| **B6** | OMC keep-policy reverts via `git reset --hard` (`runtime.ts:1221-1223`) — but OMX candidates are RL **checkpoints not in git**. | **Hybrid revert target.** config/hyperparam edits → git revert (autoresearch native). Trained weights → `last_kept_checkpoint` pointer in `ledger.json` (keep = advance; discard = leave; **no git op on weights**). exp-loop (#6) must distinguish the two. |
| **B7** | D3 "no MCP server" vs card `url:8973`. | **Non-issue, annotate.** registry.py does not check url reachability/uniqueness; `omc.json`/`superpowers.json` use the same dead url. url = declarative metadata. D3 + §6 annotated; full analysis §11. |
| **B8** | D4 cites "훈련 시작/종료는 유저" then offers full-unattended override (rule violation, unsurfaced). | **Toggle never auto-launches training** (amended D4). Analysis/design auto; launch is queued `pending approval`. Override out-of-scope for v0.1 (§9). |

Carried high/medium fixes folded in below: **H1** (exp-init topology authored before #3 — §4.1), **H3** (Claude-free = {ingest,reduce,eval} only — §4/§5), **H4** (`.omx/` at a fixed root, resolved before `output_root` — §10), **M1/M2** (`state.json` + `manifest.json` are KEEP — §10.3), **L1** (remaining open items — §9).

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
| **`exp-analyze`** | Runtime analysis of N runs. Reads profile, runs hybrid PNG-vision + code-exec. | sciomc fan-out + evidence tags; `train-analyze` generalized to a reference adapter | **`report.md` in the permanent tree** (§10.1 `<output_root>/<run_id>/analysis/<analysis_id>/`) + promoted PNGs + evidence-tagged findings. (B3: NOT `.omx/runs/.../analysis.md`.) |
| **`exp-design`** | Propose the next experiment from analysis. | trace 3-lane → discriminating-probe | `<output_root>/<run_id>/proposals/<proposal_id>.md` (the probe = next config), `pending approval` |
| **`exp-loop`** | Semi-autonomous: propose→eval→keep/discard→log→repeat. "Leaving-work" toggle gates analysis/design only; **training launch is queued, never auto-fired** (D4/B8). | autoresearch evaluator-contract loop + keep-policy + max-runtime ceiling | `.omx/runs/<id>/{results.tsv, ledger.json, decision-log.md}`; keep/discard target is **config-git + checkpoint-pointer** (B6) |

`omx` CLI: `omx ingest`, `omx reduce`, `omx eval` are **Claude-free, unit-testable** (pure Python via Bash). `omx analyze` and `omx loop` are **Claude-required** — analyze uses PNG-vision (§5), loop calls analyze (H3). So: unit tests cover {ingest, reduce, eval, paths}; analyze/loop need Claude integration tests. Skills are thin Claude wrappers that orchestrate the Claude-free verbs + read PNGs back via vision.

**Evaluator score↔policy (B5):** `omx eval` parses the evaluator's last stdout line as `{pass: bool, score?: number}` (loud-fail on bad JSON, per `contracts.ts:178-201`). `score` is **optional under `keep_policy=pass_only`** but **required under `score_improvement`** (`runtime.ts` silently discards score-less candidates otherwise). The Isaac Lab reference evaluator ships `pass_only` by default; the score formula (D5) is filled by exp-init later.

### 4.1 exp-init interview topology (resolves H1 — must be authored before building #3)

deep-interview has **exactly 3 weighted dimensions** (greenfield: Goal 0.40 / Constraints 0.30 / Criteria 0.30; brownfield adds Context 0.15; `deep-interview/SKILL.md:318-319`), an ambiguity gate `1 − Σ(wᵢ·clarityᵢ) ≤ threshold`, and a `pending approval` label on the output (the real gate = threshold + explicit user approval of an execution path). OMX maps its 5 experiment topics onto these 3 dimensions (NOT a new 5-dim vector — reuse the proven gate):

| exp-init topic | → deep-interview dim | Sample gating question |
|:--|:--|:--|
| **objective** (what is this research optimizing?) | Goal (0.40) | "What single quantity should the next experiment move, and in which direction?" |
| **eval-method** + **success-criteria** | Criteria (0.30) | "What command produces the verdict, and what numeric threshold = success?" (→ `evaluator.sh`) |
| **metrics** (axes/vocab) + **launch-recipe** (GPU/command/constraints) | Constraints (0.30) | "Which metric axes matter, and what is the exact training command + GPU gate?" (→ `metrics.yaml`, `launch.sh`) |

The interview itself is **interactive** (human answers every round — `deep-interview` asks ONE question at a time; this is NOT the autonomous part — H2). Only post-profile exp-loop execution is toggle-autonomous. D5's score-formula elicitation rides on the Criteria dimension: exp-init surfaces past-run CV-vs-per-axis-spread from existing data and lets the user pick the aggregation. Threshold + exact weights are inherited from deep-interview defaults unless the user overrides; that inheritance is what makes exp-init buildable test-first (concrete gate, concrete questions).

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

**On the `url` field (B7):** kept as `http://localhost:8973/omx` for schema parity with `omc.json`/`superpowers.json`, but it is **declarative omha-registry metadata, not a live endpoint** — nothing listens on 8973 (verified against `omc.json`, which uses the same dead url). `registry.py:65-81` reads only the named required fields and does **not** check url reachability or uniqueness, so a dead url validates. This is fully consistent with D3 "no MCP server." The note lives here in prose (not as a JSON key) because `route_emit.py` reads the raw card JSON directly (`registry.py:4-5`) and a stray key could leak into the injected router text. Full self-vs-shared MCP rationale: §11.

---

## 7. claudebase installer entry

Alongside oms/omd/omc/superpowers: add OMX marketplace + install step; **pin OMC to a known version/commit** so upgrades are intentional. On any OMC bump, re-check `cards/omx.json` still doesn't collide (it won't, by §6).

---

## 8. Build order (proposed — for the next planning pass)

**Corrected order (post-review — B4 fixed the #2↔#4 inversion; exp-init moved before exp-analyze because analyze reads the profile init writes):**

0. **`omx_paths.py` — the path single-source-of-truth FIRST** (§10). **Structural tier only** (B1): fixed-regex ids (`analysis_id`/`proposal_id`/`session_id`, generic `run_id`), loud-fail validation, mandatory `session_id` for scratch (source per B2), optional `Profile` param for the later vocabulary tier. Everything else imports paths only from here. **Pure-Python, fully unit-testable Claude-free** — no profile needed at test time.
1. `omx-core` skeleton: ingest adapters + reduce (summary-stat/downsample/plot) + `.omx/` state schema (all paths via #0). **Claude-free subset = {ingest, reduce, eval}** (H3) — unit-tested via `omx` CLI.
2. **Evaluator-contract runner + Isaac Lab REFERENCE profile** (B4 re-scope): consumes a *committed* reference `evaluator.sh` (NOT a user-elicited one), parses `{pass, score?}` (`contracts.ts:178-201`), wires keep-policy. Score required only under `score_improvement`; reference ships `pass_only` (B5). **Decide before coding: keep/discard target = config-git-revert + checkpoint-pointer (B6).**
3. **`exp-init` skill (MOVED earlier, was #4)** — interview topology authored per §4.1 (H1) → bootstraps `.omx/profile/{evaluator.sh, metrics.yaml, rules.md, launch.sh}`; resolves `.omx/` root + `output_root` bootstrap (H4). **Interview is interactive** (not the autonomous part — H2).
4. **`exp-analyze` skill (was #3)** — hybrid router §5; **Claude-required** (PNG-vision, H3). Reads the profile written by #3 → activates the B1 vocabulary tier (metric/view validation). Validate on real eval_dr runs.
5. `exp-design` skill (trace 3-lane → discriminating probe).
6. `exp-loop` skill (autoresearch loop + leaving-work toggle + 1-GPU serialization + nvidia-smi gate). **Gated on B6 (revert target) + B8 (launch is queued, never auto-fired).**
7. `cards/omx.json` + omha registration + claudebase installer entry + OMC version pin. **Already SOUND** (card-schema verdict); only needs the B7 declarative-url prose note. Buildable independently at any time.

---

## 10. Directory & naming discipline (core feature — D8)

Three principles, each enforced by code (not by agent goodwill):

1. **Physical split: user-output vs agent-intermediate.** Like git tracked/untracked. Permanent, human-facing artifacts (analysis reports, plots, next-experiment proposals) live in a clean run-id tree. One-shot agent scratch (temp plots, parse caches, scratch scripts) is quarantined under `.omx/`.
2. **`.omx/` itself has a FIXED schema** — not "it's temp so whatever." Intermediates only ever land in pre-declared slots; the structure never varies run-to-run. Enforced by a single path module (`omx_paths.py`) so an agent physically cannot write "somewhere random". Mirrors repo `paths.py:135/262` single-truth rule.
3. **Cleanup is a review-gated ritual** — never auto-delete. On "work complete" judgment or explicit user request: classify → dry-run → show diff → get approval → move to trash (never `rm`). Mirrors repo `model-trim-disaster` lesson (numeric sort, dry-run mandatory).

### 10.1 Permanent output tree — root chosen by `exp-init`, layout fixed by core

**`.omx/` root location (H4 — resolved before anything writes a profile):** `.omx/` itself lives at a **fixed location — the cwd (or the nearest enclosing repo root), resolved by `omx_paths.py` independently of and BEFORE `output_root`**. `.omx/` is NEVER under `output_root` (that would be a bootstrap chicken-egg: exp-init must write `.omx/profile/metrics.yaml` *containing* `output_root` before `output_root` is known). So: `.omx/` = fixed anchor; `output_root` = a value stored *inside* `.omx/profile/metrics.yaml`, pointing at the permanent tree (which may be elsewhere).

`exp-init` writes `output_root` into `.omx/profile/metrics.yaml`. The **layout under that root is core-fixed** (the user picks only *where the root is*, never *how it's shaped* — that's the discipline). Default root = repo `experiments/` (matches existing eval_dr convention); profile may override.

**Plot routing (B3 — promotion rule):** exp-analyze writes ALL candidate PNGs to the volatile `scratch/<session_id>/plots/` first. Only plots actually referenced in the final `report.md` are **promoted** (atomic `os.replace`) into the permanent `analysis/<analysis_id>/plots/`. Un-referenced candidates stay in scratch and are swept by `omx clean`. This is the single decision that keeps the permanent tree clean: the human deliverable (`report.md` + its promoted plots) is the ONLY thing that reaches `output_root`; everything the agent merely *looked at* stays quarantined.

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
│   └── <session_id>/                   # session-isolated, concurrent-safe (B2: OMX-native source, NOT an OMC dependency)
│       ├── plots/                      # throwaway PNGs the agent looked at but user won't keep
│       ├── py/                         # scratch analysis scripts the agent generated
│       └── notes.md                    # agent working notes for THIS session only
├── registry/                          # PERMANENT — grep-able discovery index
│   ├── INDEX.md                        # one line per analysis/proposal (id · type · date · summary · path)
│   └── findings/                       # wiki-style keyword+tag findings store (no embeddings)
│       └── <slug>.md
└── state.json                          # OMX mode state (active loop?, current_phase, session_id) — single GLOBAL file (M1: KEEP, never swept)
```

**Lifecycle separation (why 2-axis):** the repo already runs concurrent multi-GPU sessions (`concurrent-session-albc-marinelab` memory). `runs/<run_id>/cache/` is run-bound (two sessions analyzing the same run share it safely — read-mostly, content-addressed by `<source>__<metric>`). `scratch/<session_id>/` is session-bound (each session's throwaway is isolated — concurrent sessions never clobber each other's scratch).

**Path enforcement (`omx_paths.py` — single source of truth):**
- the ONLY way to get any `.omx/` or output path. No string-concatenation of paths anywhere else in the codebase (lint rule / review gate).
- every getter validates the id against its regex before returning; bad id → raise (loud-fail, never silent-fallback — repo's silent-eval-path-fallback accident lesson).
- `session_id` is **mandatory** for any `scratch/` path (prevents cross-session leak). **Source (B2 — OMX-native, no OMC dependency), 3-step precedence:** `--session-id` CLI flag → `OMX_SESSION_ID` env var → auto-generate `<YYYYMMDD-HHMMSS>-<pid>`. The skill layer passes the Claude session id via `--session-id`; the standalone CLI falls back to env then auto-gen. `omx_paths.get_scratch_path()` raises if `session_id` is empty/None (loud-fail).
- **two-tier validation (B1):** structural regexes (ids) are checked unconditionally and need no profile. Vocabulary checks (metric/view ∈ `metrics.yaml`, run_id ∈ profile regex) run only when an optional `Profile` object is passed in; absent a profile, getters do structural-only — this is what makes `omx_paths.py` unit-testable in isolation (#0) while still loud-failing on bad vocab once a profile exists (after #3).

### 10.3 Cleanup ritual (`omx clean` — review-gated, never auto-delete)

Trigger: agent judges "work complete" OR user says "정리해줘". Never fires on its own without surfacing.

```
omx clean [--scope session|run|all] [--apply]
```

1. **Classify** every `.omx/` path into: KEEP (profile/, registry/, runs/*/{results.tsv,ledger.json,decision-log.md}, **state.json (M1), and the entire permanent output tree's manifest.json (M2)**) vs SWEEP (scratch/<sid>/, runs/*/cache/, orphaned .tmp). NOTE the permanent `output_root` tree is **never reachable by `omx clean`** — cleanup operates strictly inside `.omx/`; manifest.json/report.md/promoted-plots there are safe by construction.
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

- **Score formula** (mean+λ·CV vs per-axis worst-case, λ, DR-level weighting) — deliberately deferred; `exp-init` elicits it per-profile using past-run data (D5). Elicitation rides the Criteria dimension (§4.1).
- **Deployment packaging** — marketplace repo name, whether `omx-core` ships on PyPI vs vendored in the plugin.
- **1-GPU vs tournament** parallelism in `exp-loop` — autoresearch sequential by default; self-improve tournament only if multi-GPU later.
- **(B6 carry) exp-loop revert semantics** — config edits via git revert + weights via `last_kept_checkpoint` pointer is the LOCKED direction, but the exact `ledger.json` pointer schema + how a discard "leaves" a checkpoint without orphaning disk is owed at build time of #6.
- **(B8 carry) full-unattended training override** — v0.1 forbids auto-launch entirely (D4). A future opt-in (explicit, separately-logged, per-session user authorization that de-escalates the "훈련 시작/종료는 유저" rule for OMX-scoped runs) is deliberately OUT of scope and tracked here.
- **(H4 carry) `.omx/` root resolution policy** — "cwd or nearest enclosing repo root" is locked in §10.1, but the exact discovery rule (walk up for `.git`? for an existing `.omx/`? honor an `OMX_ROOT` env?) is an `omx_paths.py` detail to pin in #0's tests.
- **(MCP) self-built MCP promotion trigger** — §11 rejects both shared and self-built MCP for v0.1. The *condition* that would justify revisiting a self-built server (OMX evolving into interactive-iterative multi-turn analysis where a persistent kernel pays off) is named but not thresholded.
```
```

> Reference paths (verified this session): OMC patterns — `marketplaces/omc/{src/autoresearch/{contracts,runtime}.ts, skills/{deep-interview,sciomc,trace,self-improve}/SKILL.md, src/tools/*-tools.ts}`. omha — `marketplaces/heroacademia/{src/omha/registry.py, hooks/{route_emit,cross_lane_emit}.py, cards/{omc,superpowers}.json}`. Token economics — Anthropic pricing/vision docs (Opus 4.8: 2576px / ~4784 tok cap).

---

## 11. MCP: self-built vs shared vs none (analysis — answers a session question; confirms D3)

The question raised: should OMX run its **own** MCP server (self-built, like OMC's `bridge/mcp-server.cjs`) or **call OMC's shared** `t` server (esp. `python_repl`)? Ground-truthed against OMC source this session.

**What OMC actually does (verified):** OMC registers a single MCP server `t` (`.mcp.json`: `node bridge/mcp-server.cjs`), a **983 KB** bundle exposing `python_repl` + state/notepad/wiki/session_search/shared_memory. The killer feature is `python_repl` = a **persistent kernel** ("variables persist across tool calls", session-locked; `src/tools/python-repl/index.ts`) — its payoff is *not reloading large datasets across an iterative ML session*.

| Criterion | Self-built MCP (OMX-own server) | Shared MCP (call OMC `t`) | **None — D3 (chosen)** |
|:--|:--|:--|:--|
| D1 self-containment | ✅ kept | ❌ **violated** — runtime dependency on OMC tool names/signatures | ✅ kept |
| Version resilience | ⚠️ couples to MCP spec | ❌ OMC renames `python_repl` ⇒ OMX breaks; nullifies all of §2 | ✅ Bash + fileIO = most stable CC interface |
| Fit to OMX usage | persistent-kernel payoff ≈ 0 (**1 run = 1 load**) | same ≈ 0 payoff, plus the coupling cost | ✅ sufficient |
| Build/maintain cost | ❌ build + maintain an ~MB server for ≈0 benefit | low (call only) but coupling is the real cost | ✅ lowest |
| Exact arithmetic / plots | kernel-built | kernel-built | `omx` CLI shells to `python`; **disk-persistent** `.omx/runs/<id>/cache/*.parquet` replaces kernel memory — more robust (concurrent-safe, survives restart) |

**Conclusion — neither; D3 ("no MCP server") is objectively correct for OMX, and is retained.**
1. **Shared is disqualified immediately:** it violates D1 head-on. One `python_repl` signature change in OMC and OMX breaks — the entire §2 version-resilience argument collapses. Not viable for a harness whose headline property is "immune to OMC updates."
2. **Self-built keeps D1 but cost ≫ benefit:** OMC built a persistent kernel to avoid reloading large data *during iterative ML training*. OMX's pattern is "1 run = 1 load" (already noted in D3) — the kernel's payoff doesn't materialize. Building/maintaining a ~MB server for ≈0 benefit violates the D2/D3 "minimal dependency surface" principle.
3. **(B) does the same job cheaper:** exact arithmetic + plotting are met by the `omx` CLI calling `python` from Bash; when persistent state genuinely helps, the `.omx/runs/<id>/cache/*.parquet` files (already in the §10.2 schema) act as a *disk-backed* kernel — stronger than in-memory because it is concurrent-safe and survives restarts.
4. **Promotion path preserved:** D3 already notes "(B)→(A) MCP promotion is easy later." If OMX ever evolves into interactive multi-turn iterative analysis where a live kernel pays off, promote to a **self-built** server (never shared, due to D1). The door stays open; we simply don't pay the cost now.

This is why the card `url` is declarative-only (B7) and D3 is amended to spell out "neither self-built nor OMC-shared."
