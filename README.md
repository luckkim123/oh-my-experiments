# oh-my-experiments (OMX)

A **self-contained** Claude Code harness for (a) analyzing research / RL experiment results and
(b) designing the next experiment. OMX is a first-class [omha](https://github.com/luckkim123/oh-my-heroacademia)
**tier-1 lane** alongside `oh-my-claudecode` and `superpowers`.

> Status: **implemented.** 4 skills + `omx-core` Python package (paths/ingest/reduce/evaluator/decision/
> loop/ledger/report/state/profile/wiki/cli) + `omx` CLI + test suite (586 passed / 1 skipped). The
> analysis/plot/reduce paths need `numpy`/`pandas`/`matplotlib` (declared in `omx-core/pyproject.toml`).
> Runtime end-to-end through the Claude skills needs a plugin-loaded session to exercise. See
> [`docs/design/`](docs/design/) for the design of record.

## What it is

- **Self-contained.** Zero runtime dependency on OMC — OMC was studied only as a *reference* for how to build
  a harness. OMX re-implements the useful patterns in its own code, reads its own `.omx/` namespace, and is
  immune to OMC version changes.
- **Python core (`omx-core`) + thin Claude skills.** The analysis/loop logic is a framework-agnostic Python
  package runnable Claude-free via an `omx` CLI (`pip install -e omx-core/`; the analysis paths pull in
  `numpy`/`pandas`/`matplotlib`); the skills are thin orchestrators on top.
- **Lightweight runtime.** Skills + `omx` CLI + `.omx/` JSON state. No custom MCP server (the most
  version-resilient interface: Bash + file IO).
- **Discipline-first directory & naming.** A single path module (`omx_paths.py`) is the only way to construct any
  path; the `.omx/` schema is fixed (never ad-hoc); cleanup is a review-gated ritual (never auto-delete).

## The 4 skills

| Skill | Role |
|:--|:--|
| `exp-init` | Bootstrap (the "research /init") — Socratic interview writes the user profile (evaluator, metrics, rules, launch + output-tree root). |
| `exp-analyze` | Runtime analysis of N runs — PNG-vision + code-exec hybrid, evidence-tagged findings. |
| `exp-design` | Propose the next experiment — trace-style 3-lane diagnosis → discriminating probe = next config. |
| `exp-loop` | Semi-autonomous propose→eval→keep/discard→log loop, with a "leaving-work" unattended toggle. |

## CLI verbs (gates and enforcement)

Beyond the core `ingest`/`eval`/`reduce`/`init` verbs, `omx` carries the R1 enforcement
and rigor gates as loud-fail CLI subcommands (hooks below are a convenience layer on
top, never the sole enforcement point):

| Verb | Role |
|:--|:--|
| `omx doctor` | Read-only environment preflight — install, deps, profile presence, hooks presence. |
| `omx report-verify --path <report.md>` | Strict: recompute the report's sha256 against its stamped manifest; rc 2 on any deviation. |
| `omx report-review --path <report.md>` | Deterministic critic checklist over a report; records a `review.json`, never gates (spec 3.4). |
| `omx profile-seal --root <dir>` | Seal `.omx/profile/{evaluator.sh,launch.sh}` sha256 at approval time. |
| `omx proposal-lint --path <proposals/id.md>` | Loud-fail gate: an exp-design proposal must carry discriminating predictions, evidence, and references. |
| `omx probe-novelty --root <dir> --proposal <path>` | Warn-only: was this probe family already tried (wiki + past proposals)? |
| `omx wiki capture-session --root <dir> --from-report <report.md>` | Write every report `[FINDING]` as a low-confidence session-log stub. |
| `omx wiki sync-profile --root <dir>` | Regenerate the reserved `profile.md` projection from `.omx/profile/`. |
| `omx tree-codify --root <dir>` | Infer `.omx/profile/tree.yaml` from an existing tree (census-based, pending approval). |
| `omx tree-audit --root <dir>` | Validate the output trees against `tree.yaml` (report-only; `--strict` escalates to rc 2). |
| `omx tree-scaffold --root <dir> --under <path>` | Mint a run skeleton or eval leaf per `tree.yaml` (refuses existing leaves; never launches). |
| `omx tree-alias --root <dir> --name <n> --run <spec>` | Create/re-point a declared alias symlink to a run (atomic; refuses undeclared names). |
| `omx tree-index --root <dir>` | Regenerate the generated `INDEX.md` at the index root (marker-guarded; `--check` reports staleness). |
| `omx clean --root <dir>` | Review-gated `.omx` cleanup: classify → dry-run → `--apply` moves to `.omx/.trash` (never `rm`). |
| `omx campaign-init --root <dir> --id <id>` | Create `.omx/campaigns/<id>/` (plan.json + empty ledger). |
| `omx campaign-log --root <dir> --id <id> --event <e>` | Append one event (launched/kept/discarded/eval/note) to the campaign ledger. |
| `omx campaign-status --root <dir> --id <id>` | Aggregate one campaign's ledger. |
| `omx campaign-list --root <dir>` | List campaigns with event counts. |
| `omx run-seed --root <dir> --run-id <id> --baseline-commit <sha> --keep-policy <p>` | Seed the run ledger with the baseline anchor (once — loud-fail if it exists). |
| `omx run-record --root <dir> --run-id <id> --iteration <n> --decision <d> ...` | Record one loop iteration into the ledger; asserts the run-lease by session id and performs the git-ancestry staleness check. |
| `omx loop-health --root <dir> --run-id <id>` | Circuit check over the run ledger: rc 2 when the plateau/fault streak trips (the authoritative stop). |
| `omx loop-mark-done --root <dir> --run-id <id> --reason <r>` | Write the loop-completion marker for an unarmed single-pass flow (an armed loop marks automatically on disarm). |
| `omx loop-status --run-id <id>` / `omx loop-status --all` | Report deadline-ceiling + pending-launch + `phase` (`done`/`running`/`died`/`idle`) as JSON, one run or every run under `runs/*/`. |
| `omx revert-config --root <dir> --cwd <repo> --run-id <id> [--to baseline\|last-kept\|<sha>] [--i-approve-revert]` | Two-phase config revert to a run's baseline/last-kept commit; dry-run by default, applies only with `--i-approve-revert`. |
| `omx campaign-plan-add --root <dir> --id <id> --proposal-id <id>` | Record a planned proposal into `plan.json`'s `planned` list (intent); status is derived at read time by `campaign-status`. |
| `omx card-check [--card <path>] [--plugin-root <path>]` | Cross-repo card-currency guard: `card.version == plugin.json.version` + every plugin skill mentioned in the card. rc 2 on drift; run at release time (the card lives in the omha repo, so this is not a pytest). |
| `omx wiki delete <slug>` | DEPRECATED — always errors (rc 2) with a JSON redirect to `wiki gc` / `wiki gc-apply`. There is no page delete (append-merge, INV-2; removal is git-guarded gc). |

`omx eval --root <dir>` additionally runs the profile-seal preflight when `--root` is
given, warning (never hard-failing in R1) on a missing or drifted seal.

### Threshold overrides

Some gates read optional override keys from `metrics.yaml` at the call boundary
(the same pattern as `wiki_quality_floor`):

| Key | Default | Read by |
|:--|:--|:--|
| `plateau_discards` | 5 | `omx loop-health` — consecutive discards before the plateau circuit trips. |
| `fault_streak` | 3 | `omx loop-health` — consecutive evaluator faults before the fault circuit trips. |
| `lock_stale_hours` | 2 | `omx_core.lock.acquire_run_lease` — age (by `armed_at`, mtime fallback for a corrupt lease) after which a run lease is reaped. |

### Write durability

All state writes route through `omx_paths.atomic_path` (files) / `atomic_dir`
(promoted analysis directories), which are both rename-atomic AND fsync-durable
(D-R5-3): the file/tmp data is fsynced before the rename and the parent directory
entry is fsynced after, so a power loss in the write window cannot lose a
committed ledger row. Note the accepted ceiling: `atomic_dir`'s parent-dir fsync
makes the *rename* durable, not the promoted directory's file *contents*.

### Lease/marker file map

- `runs/<run_id>/.loop-lock` — the session-keyed O_EXCL run lease (CLI-invocation ownership; reaped on age alone).
- `runs/<run_id>/loop-status.json` — the loop-completion marker (`mark_loop_done`), folded into `loop-status`'s `phase` field.
- `.omx/state/.state-lock` — the fcntl mutex guarding every `state.json` load-mutate-save critical section.

## Hooks and the report-reviewer agent

A fail-open `PreToolUse` hook on `Edit|Write` blocks hand-editing a gated
`report.md`/`report.ko.md` once it exists — any change goes through the skill's
RE-analysis path instead, so the format/evidence gates always run. Hooks never hard-block
on their own error: `OMX_DISABLE=1` disables all omx hooks, `OMX_SKIP_HOOKS=<names>`
disables named handlers only, and every guarantee the hooks enforce is also carried by
a loud-fail CLI verb above, so a disabled hook degrades to "not yet caught," not "not
enforced." Separately, `report-reviewer` is a read-only agent (author != reviewer)
dispatched by `exp-analyze` after the coverage gates pass — it runs `omx report-review`
first, then judges what code cannot (evidence-to-claim correspondence, earned vs.
asserted confidence, narrative consistency), returning a verdict the calling session
applies through the same RE-analysis path.

## Hooks

Five registrations in `.claude-plugin/plugin.json`, all dispatched through the
single `hooks/run_hook.py` runner:

| Event | Matcher | Handler | Role |
|:--|:--|:--|:--|
| `PreToolUse` | `Edit\|Write` | `report_guard` | Blocks hand-editing a gated `report.md`/`report.ko.md`. |
| `UserPromptSubmit` | — | `route_emit` | Injects the `<omx-routing>` STAGE checkpoint on every prompt. |
| `SessionEnd` | — | `capture_flush` (async) | Rescues any report produced but never explicitly captured into the wiki. |
| `SessionStart` | `compact` | `compact_breadcrumb` | Carries a durable-state pointer into the first post-compaction prompt (`PreCompact` has no `additionalContext` channel). |
| `Stop` | — | `loop_gate` | Thin gate for an armed exp-loop: blocks a turn from ending with a continuation prompt until disarmed or self-expired. |

Hooks never hard-block on their own error: any exception, timeout, or malformed
input exits 0 (fail-open), each handler has its own SIGALRM budget in
`run_hook.py`, and `OMX_DISABLE=1` disables all omx hooks while
`OMX_SKIP_HOOKS=<name>,<name>,...` disables named handlers only. Every
guarantee a hook enforces is also carried by a loud-fail CLI verb (D9): a
disabled or misfiring hook degrades to "not yet caught," never "not enforced."

`loop_gate`'s continuation prompt never instructs a training launch, regardless
of how the loop is armed (D4) — `omx queue-launch` remains the only
training-adjacent verb, and it only ever writes a pending-approval artifact.

Because pytest cannot exercise real platform hook firing, `.superpowers/sdd/live-acceptance.md`
is the checklist a human runs after a plugin reinstall to confirm each
registration actually fires and honors its contract.

The Stop gate now runs its state-mutation under the state mutex and carries a
best-effort circuit backstop (plateau/`fault_circuit`) that fail-opens on any
ledger-read error — the authoritative circuit stop is the `omx loop-health`
verb + exp-loop step 4.5, not the gate. Separately, `revert-config` is dry-run
by default and mutates only with `--i-approve-revert`; it is never reachable
from a hook (D4).

## Layout

```
oh-my-experiments/
├── .claude-plugin/        # plugin.json — 4 skills, no MCP
├── skills/                # exp-init / exp-analyze / exp-design / exp-loop
├── omx-core/              # pure-Python package + pyproject.toml
│   ├── omx_core/          #   omx_paths · ingest/ · reduce/ · evaluator · decision · loop
│   │                      #   · ledger · report · state · profile (tree.yaml) · wiki/ · cli
│   └── tests/             #   Claude-free unit tests (pytest)
├── cards/                 # omha tier-1 lane card (placeholder)
└── docs/
    └── design/            # design doc (source of truth)
```

## Links

- Design doc: [`docs/design/2026-05-30-omx-experiment-harness-design.md`](docs/design/2026-05-30-omx-experiment-harness-design.md)
- omha (router/installer): https://github.com/luckkim123/oh-my-heroacademia
