# oh-my-experiments (OMX)

A **self-contained** Claude Code harness for (a) analyzing research / RL experiment results and
(b) designing the next experiment. OMX is a first-class [omha](https://github.com/luckkim123/oh-my-heroacademia)
**tier-1 lane** alongside `oh-my-claudecode` and `superpowers`.

> Status: **DESIGN — pre-implementation.** No runtime code yet. See [`docs/design/`](docs/design/) for the
> locked design. The next session reviews the plan **before** implementing.

## What it is

- **Self-contained.** Zero runtime dependency on OMC — OMC was studied only as a *reference* for how to build
  a harness. OMX re-implements the useful patterns in its own code, reads its own `.omx/` namespace, and is
  immune to OMC version changes.
- **Python core (`omx-core`) + thin Claude skills.** The analysis/loop logic is a framework-agnostic Python
  package runnable Claude-free via an `omx` CLI; the skills are thin orchestrators on top.
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

## Layout (planned)

```
oh-my-experiments/
├── .claude-plugin/        # plugin.json — skills + (no MCP), omha-registered lane
├── skills/                # exp-init / exp-analyze / exp-design / exp-loop
├── omx-core/              # pure-Python package: omx_paths, ingest, reduce, analyze, evaluator, loop
├── cards/                 # omx.json (the omha tier-1 lane card)
├── docs/
│   └── design/            # the locked design doc (source of truth)
└── tests/                 # Claude-free unit tests for omx-core
```

## Links

- Design doc: [`docs/design/2026-05-30-omx-experiment-harness-design.md`](docs/design/2026-05-30-omx-experiment-harness-design.md)
- omha (router/installer): https://github.com/luckkim123/oh-my-heroacademia
