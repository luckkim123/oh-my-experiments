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

`omx eval --root <dir>` additionally runs the profile-seal preflight when `--root` is
given, warning (never hard-failing in R1) on a missing or drifted seal.

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

## Layout

```
oh-my-experiments/
├── .claude-plugin/        # plugin.json — 4 skills, no MCP
├── skills/                # exp-init / exp-analyze / exp-design / exp-loop
├── omx-core/              # pure-Python package + pyproject.toml
│   ├── omx_core/          #   omx_paths · ingest/ · reduce/ · evaluator · decision · loop
│   │                      #   · ledger · report · state · profile · wiki/ · cli
│   └── tests/             #   Claude-free unit tests (pytest)
├── cards/                 # omha tier-1 lane card (placeholder)
└── docs/
    └── design/            # design doc (source of truth)
```

## Links

- Design doc: [`docs/design/2026-05-30-omx-experiment-harness-design.md`](docs/design/2026-05-30-omx-experiment-harness-design.md)
- omha (router/installer): https://github.com/luckkim123/oh-my-heroacademia
