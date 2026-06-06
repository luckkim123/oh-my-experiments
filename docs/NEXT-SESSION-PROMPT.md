# OMX next-session start prompt — OMX v0.1 SHIPPED (awaiting post-v0.1)

> Written: 2026-05-31 (right after #7 finalize/deploy + deployment verification completed).
> HEAD = main `d37eb1e` + subsequent docs commits. origin/main **synced (0 unpushed)**.

---

## Status: OMX v0.1 COMPLETE

Entire build-order (#0~#8) DONE + #7 finalize/deploy + deployment verification PASS. **Awaiting new requests.**

- The 4-skill set (exp-init/analyze/design/loop) + the Claude-free `omx` core + workspace-wiki (build #8) are all deployed and verified.
- The registration infrastructure (omha card + routing / claudebase settings.json + install.sh / OMC v4.14.4 pin) and the OMX repo proper are all pushed to origin.
- Deployment verification end-to-end PASS: fresh clone → `pip install -e` → run all `omx` CLI verbs → wiki 4-verb (latin+CJK query / append-merge lossless / lint) → discover the 4 skills. leak-scan 0 hits. 366 passed/1 skipped.

---

## Post-v0.1 follow-up candidates (on request)

design `docs/design/2026-05-30-omx-experiment-harness-design.md` §9 open items:
- **score-formula real-profile elicit** (mean+λ·CV vs per-axis worst-case) — exp-init elicits D5 from real past-run data.
- **1-GPU vs tournament** parallelism (exp-loop) — once multi-GPU is available, self-improve tournament.
- **MCP promotion trigger** — if OMX evolves into interactive-iterative, a self-built MCP (a shared OMC MCP is permanently rejected, D1).
- **legacy results migration** — migrate scattered results into the `/workspace/docs/results/` schema (repo rule 02-operations, owed).
- **real-data dogfood** — bootstrap a real isaaclab/eval_dr profile with exp-init, then validate exp-analyze with a real run.

## Constraints (if continued)
- Respond in the user's language; code/markdown in English; no emojis; no AI attribution (git trailer only is the exception).
- push is gated on explicit user approval. When editing claudebase, `git pull` first ([[claudebase-pull-before-register]]).
- `python3` (NOT `python`). dist `omx-core/` (hyphen) vs pkg `omx_core/` (underscore). `pip install -e .`→`--break-system-packages`.
- Tests: `cd omx-core && python3 -m pytest tests/ -q` (baseline 366 passed/1 skipped).

## Read first
1. `docs/HANDOFF.md` — v0.1 SHIPPED record + full build-order detail.
2. `docs/design/2026-05-30-omx-experiment-harness-design.md` — source of truth (§9 open items).
3. memory `omx-build8-workspace-wiki-2026-05-31` (v0.1 SHIPPED).
