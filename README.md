# oh-my-experiments (OMX)

A **self-contained** Claude Code harness for (a) analyzing research / RL experiment results and
(b) designing the next experiment. OMX is a first-class [omha](https://github.com/luckkim123/oh-my-heroacademia)
**tier-1 lane** alongside `oh-my-claudecode` and `superpowers`.

> Status: **v0.1.0 — implemented.** 4 skills + `omx-core` Python package (13 modules: paths/ingest/reduce/
> evaluator/decision/loop/ledger/report/state/profile/wiki/cli) + `omx` CLI + test suite. Heavy-dep-free
> tests pass (135 passed); the analysis/plot/reduce paths need `numpy`/`pandas`/`matplotlib` (declared in
> `omx-core/pyproject.toml`). Runtime end-to-end through the Claude skills needs a plugin-loaded session to
> exercise. See [`docs/design/`](docs/design/) for the design of record.

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

## Layout

```
oh-my-experiments/
├── .claude-plugin/        # plugin.json (v0.1.0) — 4 skills, no MCP
├── skills/                # exp-init / exp-analyze / exp-design / exp-loop
├── omx-core/              # pure-Python package + pyproject.toml (omx-core, v0.1.0)
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
