# oh-my-experiments (OMX)

> A self-contained Claude Code harness that **analyzes your ML/RL training runs, diagnoses regressions, and designs the next experiment** — with a semi-autonomous analyze → design → eval loop that never fires a training run without your approval.

![version](https://img.shields.io/badge/version-0.7.4-blue)
![python](https://img.shields.io/badge/python-%3E%3D3.10-blue)
![tests](https://img.shields.io/badge/tests-950%20passed%20%2F%201%20skipped-brightgreen)
![license](https://img.shields.io/badge/license-MIT-green)
![harness](https://img.shields.io/badge/omha-tier--1%20lane-8A2BE2)

OMX turns "why did this run regress?" and "what should I try next?" into a disciplined,
evidence-first workflow. It reads your experiment outputs, produces an evidence-tagged
report, proposes a single discriminating next experiment, and can loop the whole cycle
while you are away — queuing the next training launch as a pending-approval artifact
rather than launching it.

It is a first-class [omha](https://github.com/luckkim123/oh-my-heroacademia) **tier-1 lane**
alongside `oh-my-claudecode` and `superpowers`, but carries **zero runtime dependency** on
any other harness.

---

## Table of contents

- [Why OMX](#why-omx)
- [Quick start](#quick-start)
- [The four skills](#the-four-skills)
- [How it works](#how-it-works)
- [Configuration](#configuration)
- [CLI reference](#cli-reference)
- [Hooks & review agents](#hooks--review-agents)
- [Project layout](#project-layout)
- [Development](#development)
- [License](#license)

---

## Why OMX

| | |
|:--|:--|
| **Evidence, not vibes** | Every finding in a report is tagged to code-exec stats or a vision-read plot. Proposals must carry discriminating predictions or the gate rejects them. |
| **Never launches training** | The loop analyzes, designs, and evaluates; the next launch is always a pending-approval artifact (`omx queue-launch`). No hook and no loop can fire a real training run. |
| **Self-contained** | A pure-Python core (`omx-core`) + a thin `omx` CLI + `.omx/` JSON state. No custom MCP server — the most version-resilient interface is Bash + file IO. Immune to other harnesses' version churn. |
| **Discipline-first** | One path module is the only way to construct any path; the `.omx/` schema is fixed (never ad-hoc); cleanup is a review-gated ritual that moves to `.omx/.trash`, never `rm`. |
| **Every guarantee is CLI-enforced** | Hooks are a convenience layer. Each guarantee a hook provides is *also* carried by a loud-fail CLI verb, so a disabled hook degrades to "not yet caught," never "not enforced." |

## Quick start

**Prerequisites:** Python ≥ 3.10, and [Claude Code](https://claude.com/claude-code) v2.1.3 or later
for the skills (the plugin's `SessionEnd` hook needs v1.0.85+, and its skill `argument-hint`
frontmatter needs the v2.1.3 unification of skill/slash-command frontmatter — v2.1.3 is the
higher, binding floor of the two).

### 1. Install the CLI

```bash
# Core CLI + analysis stack (numpy / pandas / matplotlib / pyyaml)
pip install -e omx-core/

# Optional: W&B / TensorBoard ingest support
pip install -e "omx-core/[analyze]"

# Verify the environment
omx doctor
```

`omx doctor` is a read-only preflight — it reports install, dependency, profile, and hook presence, and never mutates anything.

### 2. Install the plugin

OMX ships as a Claude Code plugin via the heroacademia marketplace (plugin
`oh-my-experiments`):

```bash
claude plugin marketplace add https://github.com/luckkim123/oh-my-heroacademia.git
claude plugin install oh-my-experiments@heroacademia
```

Once loaded, the four skills below auto-route from natural-language prompts ("analyze
these runs", "다음 실험 설계해줘").

### 3. Bootstrap a project

```
exp-init  <one-line description of your research>
```

`exp-init` runs a Socratic, ambiguity-gated interview and writes your profile to
`.omx/profile/` — the optimization objective, eval method, metric vocabulary, and launch
recipe. Then:

```
exp-analyze  <run ids or result paths>      # → evidence-tagged report.md
exp-design   <path to report.md>            # → proposals/<id>.md (the next experiment)
exp-loop     <run_id> [--max-runtime <s>]   # → the semi-autonomous cycle
```

## The four skills

| Skill | Role | Writes |
|:--|:--|:--|
| **`exp-init`** | Bootstrap — the "research `/init`". An ambiguity-gated Socratic interview elicits objective, eval method, success criteria, metric vocabulary, and launch recipe. | `.omx/profile/{evaluator.sh, metrics.yaml, rules.md, launch.sh}` (pending approval) |
| **`exp-analyze`** | Analyze N runs into an evidence-tagged report. A hybrid router decides *per question* between exact code-exec stats and a vision-read PNG curve. Never launches training/eval. | `report.md` + promoted plots (the permanent analysis tree) |
| **`exp-design`** | Design the next experiment. A 3-lane differential diagnosis (code-path / config-DR-hyperparam / measurement-artifact) yields one discriminating probe = the next config. | `proposals/<id>.md` (pending approval) |
| **`exp-loop`** | Semi-autonomous analyze → design → eval → keep/discard → log, until a deadline or stop condition. The "leaving-work" deadline governs only analyze/design/eval; the next launch is **queued, never fired**. | run ledger + `queue-launch` artifact |

## How it works

```
                 ┌───────────┐  profile (evaluator, metrics, launch recipe)
   exp-init ────▶│   .omx/    │
                 │  profile   │
                 └─────┬─────┘
                       │
   runs/ ───▶ exp-analyze ───▶ report.md ───▶ exp-design ───▶ proposals/<id>.md
   (your training     │  (evidence-tagged)      (3-lane diagnosis   (discriminating
    outputs)          │                          → one probe)        next experiment)
                      │                                │
                      └────────────── exp-loop ────────┘
                        keep / discard / log · queue-launch (pending approval)
```

Everything is persisted as JSON under `.omx/` and every mutation is auditable. The
report *is* the deliverable of analysis; the proposal *is* the deliverable of design —
there is no separate hand-written summary step.

## Configuration

OMX reads a small set of environment variables. All are optional.

| Variable | Effect |
|:--|:--|
| `OMX_DISABLE=1` | Disables **all** omx hooks (every guarantee is still carried by a CLI verb). |
| `OMX_SKIP_HOOKS=<name>,<name>` | Disables named hook handlers only. |
| `OMX_STATE_DIR=<dir>` | Overrides the `.omx/` state root location. |
| `OMX_PROJECT_DIR=<dir>` | Overrides the project root used for path resolution. |
| `OMX_SESSION_ID=<id>` | Overrides the session id (the run-lease ownership key). |
| `OMX_NO_ROOT_LADDER=1` | Disables the parent-directory ascent when locating an `.omx/` root. |

Some gates read optional override keys from `metrics.yaml` at the call boundary:

| Key | Default | Read by |
|:--|:--|:--|
| `plateau_discards` | 5 | `omx loop-health` — consecutive discards before the plateau circuit trips. |
| `fault_streak` | 3 | `omx loop-health` — consecutive evaluator faults before the fault circuit trips. |
| `lock_stale_hours` | 2 | `omx_core.lock.acquire_run_lease` — age after which a stale run lease is reaped. |

## CLI reference

Beyond the core `ingest` / `eval` / `reduce` / `init` verbs, the `omx` CLI carries the
enforcement and rigor gates as loud-fail subcommands. The full surface is below — most
users only need the four skills above.

<details>
<summary><b>Core & analysis</b></summary>

| Verb | Role |
|:--|:--|
| `omx doctor` | Read-only environment preflight — install, deps, profile, hooks. |
| `omx init` | Initialize the `.omx/` state root. |
| `omx ingest` | Ingest run outputs (CSV long-form, eval summaries, TensorBoard, W&B offline). |
| `omx reduce {summarize,tb-final}` | Reduce ingested series into summaries / final-step tables. |
| `omx eval --root <dir>` | Run the profile evaluator; runs the profile-seal preflight when `--root` is given (warns on a missing/drifted seal). |
| `omx plot` / `omx promote-plots` | Render and promote plots into the analysis tree. |
| `omx session-id` | Print the current session id (run-lease ownership key). |

</details>

<details>
<summary><b>Report & proposal gates</b></summary>

| Verb | Role |
|:--|:--|
| `omx report-parse` | Structured read of a `report.md` (never hand-parse a report). |
| `omx report-verify --path <report.md>` | Strict: recompute the report's sha256 against its stamped manifest; rc 2 on any deviation. |
| `omx report-coverage` | Check a report's coverage stamp. |
| `omx report-review --path <report.md>` | Deterministic critic checklist; records a `review.json`, never gates. |
| `omx proposal-lint --path <proposals/id.md>` | Loud-fail gate — a proposal must carry discriminating predictions, evidence, and references. |
| `omx probe-novelty --root <dir> --proposal <path>` | Warn-only: was this probe family already tried (wiki + past proposals)? |
| `omx profile-seal --root <dir>` | Seal `.omx/profile/{evaluator.sh,launch.sh}` sha256 at approval time. |

</details>

<details>
<summary><b>Loop, lease & revert</b></summary>

| Verb | Role |
|:--|:--|
| `omx queue-launch --cwd <repo>` | Write a pending-approval training-launch artifact (records `queued_commit` provenance). **The only training-adjacent verb.** |
| `omx loop-arm` / `omx loop-disarm` | Arm / disarm a semi-autonomous loop. |
| `omx loop-status [--run-id <id> \| --all]` | Deadline-ceiling + pending-launch + `phase` (`done`/`running`/`died`/`idle`) as JSON. |
| `omx loop-health --root <dir> --run-id <id>` | Circuit check over the run ledger — rc 2 when the plateau/fault streak trips (the authoritative stop). |
| `omx loop-mark-done --root <dir> --run-id <id> --reason <r>` | Write the loop-completion marker for a single-pass flow. |
| `omx run-seed ... --baseline-commit <sha> --keep-policy <p>` | Seed the run ledger with the baseline anchor (once — loud-fail if it exists). |
| `omx run-record ... --iteration <n> --decision <d>` | Record one loop iteration; asserts the run-lease by session id and runs the git-ancestry staleness check. |
| `omx revert-config --cwd <repo> --run-id <id> [--to baseline\|last-kept\|<sha>] [--i-approve-revert]` | Two-phase config revert; dry-run by default, mutates only with `--i-approve-revert`. Never reachable from a hook. |

</details>

<details>
<summary><b>Campaigns</b></summary>

| Verb | Role |
|:--|:--|
| `omx campaign-init --id <id>` | Create `.omx/campaigns/<id>/` (plan.json + empty ledger). |
| `omx campaign-log --id <id> --event <e>` | Append one event (launched/kept/discarded/eval/note) to the ledger. |
| `omx campaign-status --id <id>` | Aggregate one campaign's ledger. |
| `omx campaign-list` | List campaigns with event counts. |
| `omx campaign-plan-add --id <id> --proposal-id <id>` | Record a planned proposal into `plan.json`; status derived at read time. |

</details>

<details>
<summary><b>Output-tree discipline</b></summary>

| Verb | Role |
|:--|:--|
| `omx tree-codify --root <dir>` | Infer `.omx/profile/tree.yaml` from an existing tree (census-based, pending approval). |
| `omx tree-audit --root <dir> [--strict]` | Validate output trees against `tree.yaml` (report-only; `--strict` → rc 2). |
| `omx tree-scaffold --root <dir> --under <path>` | Mint a run skeleton / eval leaf per `tree.yaml` (refuses existing leaves; never launches). |
| `omx tree-alias --root <dir> --name <n> --run <spec>` | Create/re-point a declared alias symlink (atomic; refuses undeclared names). |
| `omx tree-index --root <dir> [--check]` | Regenerate the generated `INDEX.md` (marker-guarded; `--check` reports staleness). |
| `omx clean --root <dir> [--apply]` | Review-gated cleanup: classify → dry-run → `--apply` moves to `.omx/.trash` (never `rm`). |

</details>

<details>
<summary><b>Wiki (persistent experiment knowledge)</b></summary>

| Verb | Role |
|:--|:--|
| `omx wiki add \| query \| list \| read` | Manage the experiment knowledge base. |
| `omx wiki lint` | Lint wiki pages (quality floor via `wiki_quality_floor`). |
| `omx wiki capture-session --from-report <report.md>` | Write every report `[FINDING]` as a low-confidence session-log stub. |
| `omx wiki capture-flush` | Rescue any produced-but-uncaptured report (also the `SessionEnd` hook). |
| `omx wiki sync-profile` | Regenerate the reserved `profile.md` projection from `.omx/profile/`. |
| `omx wiki promote-recipe` | Promote a diagnosis procedure into a reusable recipe. |
| `omx wiki gc` / `omx wiki gc-apply` | Diagnose and (after approval) apply wiki garbage collection. |
| `omx card-check` | Cross-repo card-currency guard — FAILS against a stale omha routing card by design. |

</details>

### Lease / marker file map

- `runs/<run_id>/.loop-lock` — the session-keyed `O_EXCL` run lease (reaped on age alone).
- `runs/<run_id>/loop-status.json` — the loop-completion marker, folded into `loop-status`'s `phase` field.
- `.omx/state/.state-lock` — the fcntl mutex guarding every `state.json` load-mutate-save critical section.

## Hooks & review agents

Five registrations in `.claude-plugin/plugin.json`, all dispatched through the single
`hooks/run_hook.py` runner:

| Event | Matcher | Handler | Role |
|:--|:--|:--|:--|
| `PreToolUse` | `Edit\|Write` | `report_guard` | Blocks hand-editing a gated `report.md`/`report.ko.md` — edits go through the skill's RE-analysis path so the format/evidence gates always run. |
| `UserPromptSubmit` | — | `route_emit` | Injects the `<omx-routing>` STAGE checkpoint on every prompt. |
| `SessionEnd` | — | `capture_flush` (async) | Rescues any report produced but never explicitly captured into the wiki. |
| `SessionStart` | `compact` | `compact_breadcrumb` | Carries a durable-state pointer into the first post-compaction prompt. |
| `Stop` | — | `loop_gate` | Thin gate for an armed exp-loop — blocks a turn from ending until disarmed or self-expired. |

**Hooks never hard-block on their own error.** Any exception, timeout, or malformed input
exits 0 (fail-open); each handler has its own SIGALRM budget. `OMX_DISABLE=1` disables all
hooks, `OMX_SKIP_HOOKS=<name>,...` disables named handlers only. Every guarantee a hook
enforces is also a loud-fail CLI verb, so a disabled hook degrades to "not yet caught,"
never "not enforced." `loop_gate`'s continuation prompt never instructs a training launch,
regardless of how the loop is armed.

Because pytest cannot exercise real platform hook firing, `.superpowers/sdd/live-acceptance.md`
is the checklist a human runs after a plugin reinstall to confirm each registration fires
and honors its contract.

### Read-only review agents (`author ≠ reviewer`)

Four read-only agents run the "a different set of eyes" pass — dispatched by the skills,
they never edit anything and return a verdict the calling session applies:

| Agent | Reviews |
|:--|:--|
| `report-reviewer` | An `exp-analyze` report — evidence-to-claim correspondence, earned vs. asserted confidence, narrative consistency (runs `omx report-review` first). |
| `proposal-reviewer` | An `exp-design` proposal — whether the probe actually discriminates and is one variable (runs `omx proposal-lint` / `probe-novelty` first). |
| `campaign-auditor` | A campaign ledger — decision hygiene, probe novelty, run coverage. |
| `wiki-curator` | Wiki garbage-collection candidates before `gc-apply`. |

## Project layout

```
oh-my-experiments/
├── .claude-plugin/     # plugin.json (4 skills, 5 hooks) + marketplace.json
├── skills/             # exp-init / exp-analyze / exp-design / exp-loop
├── agents/             # 4 read-only review agents (report/proposal/campaign/wiki)
├── hooks/              # run_hook.py dispatch runner + handlers.py
├── scripts/            # sync_version.py — plugin.json is the version SSOT, fanned out to pyproject
├── cards/              # omha tier-1 lane card (placeholder)
├── omx-core/           # pure-Python package + pyproject.toml
│   ├── omx_core/       #   omx_paths · ingest/ · reduce/ · evaluator · decision · loop · ledger
│   │                   #   · report · state · profile (tree.yaml) · lock · revert · wiki/ · cli
│   └── tests/          #   Claude-free unit tests (pytest)
├── docs/               # design/ (source of truth) + audit/handoff notes
├── .superpowers/       # sdd/live-acceptance.md — human post-reinstall checklist
├── CHANGELOG.md
└── README.md
```

## Development

```bash
pip install -e "omx-core/[analyze]"
cd omx-core && pytest        # 950 passed, 1 skipped (v0.7.4)
```

- **Version SSOT:** `.claude-plugin/plugin.json` is the single source of truth; `scripts/sync_version.py` fans the version out to `omx-core/pyproject.toml`, and `test_version_sync.py` fails the suite on any drift.
- **Verb contract:** skill docs may only reference verbs the CLI actually registers (`test_skills_reference_real_verbs.py`).
- **Live acceptance:** hooks can't be pytest-exercised, so run `.superpowers/sdd/live-acceptance.md` after each plugin reinstall.
- **Design of record:** [`docs/design/2026-05-30-omx-experiment-harness-design.md`](docs/design/2026-05-30-omx-experiment-harness-design.md).
- **Full history:** [`CHANGELOG.md`](CHANGELOG.md) (Keep a Changelog + semver on the plugin).

## License

MIT — declared in `.claude-plugin/plugin.json`.

## Links

- **Design doc:** [`docs/design/2026-05-30-omx-experiment-harness-design.md`](docs/design/2026-05-30-omx-experiment-harness-design.md)
- **Changelog:** [`CHANGELOG.md`](CHANGELOG.md)
- **omha (router / installer):** https://github.com/luckkim123/oh-my-heroacademia
