# OMX Work Handoff (2026-05-30)

> Next session / after compact: reading just this file + `docs/design/2026-05-30-omx-experiment-harness-design.md` (source of truth)
> is enough to continue. The per-build-order execution plans are in `docs/superpowers/plans/`.

## NEXT (2026-07-11)

**R5 (v0.6.0, packaging residue) done on branch `feat/v0.6.0-r5`.** Skill-budget
test (#18), `omx wiki delete` deprecation stub (#20), fsync durability in the
atomic-write choke point (#21), the `omx_core.clock` unification that ends R4's
naive/aware `_now_iso` clock-mix, a circuit backstop that survives ledger
corruption (D-R4-4 residual), and `omx card-check` (the cross-repo card-currency
guard). PyPI-vs-vendored decided: neither — the editable install via claudebase
stays (D-R5-7). See `CHANGELOG.md` `[0.6.0]` for the full list. Suite: 892 passed,
1 skipped.

**Next = R6 (real-data dogfood + conditional promotions):** everything R5
re-deferred, still conditioned on a real-data dogfood soak that has never run (a
2026-07-11 sweep found zero `.omx` roots on any machine). Verbatim conditions
(D-R5-8):

- **warn→hard promotions** (report-review consumption gate, seal hard-fail,
  unstamped-report hard-fail) — condition: *dogfood happened*, not a release
  number.
- **candidate-commit launch-discipline hardening** (launch.sh mechanically
  records the training commit) — post-dogfood; R4's queue-time `queued_commit` +
  template instruction stand.
- **richer campaign planning** (multi-experiment DAGs, plan-level budgets) —
  post-dogfood; the intent-list + read-time join stand.
- **the dogfood soak itself is human-run** (real training runs on the user's
  machines) — `.superpowers/sdd/live-acceptance.md` is the pending entry point;
  R5 added the gate ledger-corrupt disarm + card-check-at-release checks to it.

The sections below (`## Current State (summary)` onward) are the original
v0.1-era handoff — kept for history, superseded by the CHANGELOG for R1-R3.

## Current State (summary)

Repo `<repo>`. **OMX v0.1 = all build-orders (#0~#8) DONE + #7 finalize/deploy + deployment verification complete (2026-05-31).** working tree clean, origin/main synced (0 unpushed).

### v0.1 SHIPPED (2026-05-31)
- **#7 deploy DONE + verification PASS.** Registration infra (all pushed): omx repo PUBLIC · omha `cards/omx.json` + routing (`8790bf9`) · claudebase settings.json (`oh-my-experiments@omx` + extraKnownMarketplaces `omx`) + install.sh OMX block (`d16e270`) + OMC v4.14.4 pin (`e7f6121`). OMX repo 39 commits (#5/#6/#8+docs) pushed (`fe3ee80..d37eb1e`, user-approved).
- **Deployment verification (end-to-end) PASS:** (a) anonymous clone from public origin OK; (b) fresh `pip install -e` of cloned omx-core → `omx` console entry at `/usr/local/bin/omx`, all verbs (core 10 + wiki) exposed; (c) **wiki 4-verb e2e smoke** (add→list→query→lint, isolated root): both latin+CJK (Korean 'roll') queries hit, append-merge `{"action":"updated"}` (0 overwrites · 0 loss, original + append coexist on disk in a `## Update` section), lint correctly detects broken-ref; (d) all 4 skill SKILL.md frontmatters (name+description) valid = discoverable; (e) leak-scan 0 hits (no private paths / repo names / domain terms — `isaaclab` is only the intended default profile-name/reference stub). Restored dev editable install as source-of-truth, 366 passed / 1 skipped, no regression.
- **OMX v0.1 COMPLETE.** Next work = post-v0.1 (awaiting new request). Follow-up candidates: §9 open items (score-formula real-profile elicit, 1-GPU vs tournament, MCP promotion trigger), legacy results migration.

### (History) Original scope of this session
Repo `<repo>`. **#2 work branch `feat/omx-evaluator`** (not merged into main, 8 commits `bc07337..c681b52`). working tree clean.
**This session's scope = #2 implementation + (afterward) public transition + claudebase/marketplace registration + push.** Push was explicitly requested by the user this session (the original "don't push" was retracted) — but bundled in the deploy step after #2 review is complete.

### Completed build-orders
- **#0 `omx_paths.py`** — path single-source-of-truth. 6 TDD tasks, merged (`65fe813`).
- **#1 omx-core skeleton** — ingest + reduce + CLI + state.json. 11 TDD tasks + 2-stage review + opus final review ✅ MERGE-READY. merged. **160 tests pass.**
- **#2 evaluator-contract runner + Isaac Lab reference** — ✅ **MERGE-READY** (branch `feat/omx-evaluator`, not merged · not pushed). 7 TDD tasks, each passed spec+quality 2-stage review (0 fix rounds) + opus final cross-cutting review live-verified MERGE-READY. **221 passed / 1 skipped.** plan = `docs/superpowers/plans/2026-05-30-omx-evaluator-runner.md` (4-lens adversarial review SOUND, commit `c681b52`).
  - What it builds: `evaluator.py` (parse_evaluator_result loud-fail + run_evaluator subprocess LAST-line fault-recorded) / `decision.py` (parse_keep_policy + decide_outcome keep/discard/ambiguous/bootstrap, B5) / `ledger.py` (trio writers + seed_ledger immutable baseline + record_iteration B6 pointer) / `reference/isaaclab/evaluator.sh` (pass_only stub) / `omx_paths.py` (+OmxError base, +reference_dir/reference_evaluator/checkpoint_pointer_json) / `cli.py` (+`omx eval`).
  - **B6 LOCKED**: config→git SHA (baseline_commit immutable anchor + last_kept_commit) / weights→last_kept_checkpoint pointer (keep advances, non-keep leaves, never any git/rm on weight files). checkpoint-pointer.json mirror (ledger authoritative).
  - **One Minor left by opus (not applied, can defer)**: `omx eval` outputs a non-finite score as the strict-JSON-violating `NaN` (the sibling `_cmd_reduce_summarize` has an `allow_nan=False` guard). Doesn't touch the pass_only path and doesn't crash → in #3 (score formula) add `math.isfinite` to `_is_number` + `allow_nan=False` to `_cmd_eval`.

### What #1 builds (omx-core/omx_core/)
- `omx_paths.py` (#0) — only the cache extension changed `.parquet`→`.npz` (pyarrow absent).
- `state.py` — `.omx/state.json` schema + atomic load/save (loop #6 fills the fields).
- `ingest/` — `IngestResult`/`SummaryRecord` (long-form) + `IngestAdapter` ABC; `EvalSummaryAdapter` (eval_dr summary.json), `LongFormCsvAdapter` (flat CSV), `WandbAdapter` (offline `.wandb` datastore parse) / `TensorboardAdapter` (EventAccumulator) — real adapters as of build #4, heavy imports deferred.
- `reduce/` — `summarize` (to_dataframe + add_cv=std/mean, 03-analysis-quality rule), `series` (load_npz + downsample axis-0 stride), `plot` (headless Agg PNG, width cap), `cache` (atomic npz, np.savez file-object form).
- `cli.py` — `omx` CLI: `ingest` / `reduce summarize` / `session-id` (flag>env>autogen B2). console script registered.

**Verification:** `cd omx-core && python3 -m pytest tests/ -q` → **160 passed**. Pure stdlib + numpy/pandas/matplotlib/pyyaml. 0 dependency on Claude/Isaac/network. opus final: 0 Critical/Important, coherence/path-SSOT/loud-fail audits all PASS.

### Real-data ground-truth (verified — reused in #4)
- eval_dr `summary.json` = `{dr_level: {axis: {field: float}}}`. dr_level∈{none,soft,medium,hard}, axis∈{roll,pitch,vx,vy,vz,yaw,att_norm (4 fields only), survival_pct (scalar)}, full axis = 15 fields.
- `data_*.npz` = trajectory (7750,4)=(timesteps,n_envs) + target (7750,) + time_to_failure (4,).
- pyarrow not installed → cache is `.npz`.

### What to do next (this session — resume immediately after compact)
**Deploy step (user request, bundled after #2 review is complete):** order = (a) `feat/omx-evaluator` → merge into main (finishing-a-development-branch, merge-local) → (b) transition omx repo to public → (c) claudebase + marketplace registration → (d) push to 3 places. **All outward-facing / irreversible, so a 1-line confirm right before execution.**

**Registration mechanism (recon complete — exact files · commands):**
- omx repo: `github.com/luckkim123/oh-my-experiments` currently **PRIVATE** → `gh repo edit luckkim123/oh-my-experiments --visibility public`.
- omha card: `<plugins>/marketplaces/heroacademia/cards/omx.json` newly authored (design §6 content verbatim) — glob discovery, so no index edit needed. heroacademia is a **shallow clone** (push works), remote=`luckkim123/oh-my-heroacademia`. Additionally add an oh-my-experiments entry to that repo's `.claude-plugin/marketplace.json`.
- OMX manifest: `<repo>/.claude-plugin/{plugin.json,marketplace.json}` new (skills array `[]` — before #3~#6). plugin.json: name=oh-my-experiments, version 0.1.0.
- claudebase (`<claudebase>`, remote=`luckkim123/claudebase`): `config/settings.json` (enabledPlugins `"oh-my-experiments@omx": true` + extraKnownMarketplaces `omx`) + `installer/install.sh` (OMX marketplace block + OMC version pin `pin_omc_version()`; currently OMC 4.14.1 installed / 4.14.4 cached — **pin version needs user confirmation**, sync_plugins doesn't track version so this is a separate function that reads installed_plugins.json directly).
- push to 3 places: oh-my-experiments (full clone) + oh-my-heroacademia (shallow) + claudebase.

**Afterward (next session — design §8 DAG):** #3~#8 all DONE → **#7 finalize** (cards/omx.json + omha registration + claudebase installer + OMC version pin; design §8 #7). #8 workspace-specialization wiki DONE (omx_core/wiki/ + omx wiki verbs, 365 passed / 1 skipped).

- **#4 exp-analyze — DONE + MERGED + PUSHED** (merged to `main` via no-ff `43963f9`, pushed to origin/main; branch `feat/omx-exp-analyze` deleted). What it builds: `TensorboardAdapter` (EventAccumulator real implementation) + `WandbAdapter` (offline `.wandb` datastore parse) — stub→real, heavy imports deferred, both emit a `_step/<key>` x-axis companion (one adapter contract; FINAL-review fix `a3020b6`); `load_profile` (metrics.yaml→Profile, activates B1 vocabulary tier); B3 plot-promotion core (`reduce/promote.py`) + `omx plot` / `omx promote-plots` CLI verbs; `analyze` optional-deps extra + import-safety guard tests; `skills/exp-analyze/SKILL.md` (§5 hybrid router: code-exec for exact numbers / PNG-vision for shape/overlay/eval JSON, evidence tags [FINDING]/[EVIDENCE]/[CONFIDENCE], persistent-tree records report.md/manifest.json via atomic_path). **278 passed / 1 skipped.** 2 skills registered in plugin.json (exp-init + exp-analyze); FINAL opus review = MERGE_READY. NEXT = #5 exp-design.

- **#5 exp-design — DONE** (branch `feat/omx-exp-design`, not merged · not pushed). What it builds: core `omx_core/report.py` (`Finding` dataclass + `parse_findings(text)->list[Finding]` — parser for exp-analyze report.md's `[FINDING]`/`[EVIDENCE]`/`[CONFIDENCE]` triplets; orphan · malformed · bad-keyword tag runs loud-fail with `ReportParseError`, the `_ANY_TAG` guard blocks silent-drop) + `omx report-parse` CLI verb (Claude-free, rc 0 + `{n_findings, findings:[]}` / rc 2 loud-fail) + `Finding`/`parse_findings`/`ReportParseError` export. `skills/exp-design/SKILL.md` (3-lane differential diagnosis: code-path / config-DR-hyperparam / measurement-artifact — re-implements the OMC trace pattern → evidence FOR/AGAINST + critical unknown per lane → cheapest discriminating probe = next experiment; report is read only via `omx report-parse`, hand-parse forbidden; proposal recorded via the existing `proposal_md` getter + `atomic_path` to `proposals/<TS>-next.md` in the persistent tree as pending-approval; hard gate = no auto-fire of training/eval · one-variable · track every numeric finding). **0 new core path code** (reuses proposal_md/atomic_path). **292 passed / 1 skipped.** Each task passed spec+quality 2-stage review (T2 orphan bad-keyword fix + T3 with-open/zero-findings polish). plugin.json skills = [exp-init, exp-analyze, exp-design], 3 total. NEXT = **#6 exp-loop** (also handles the #2 Minor NaN guard here).

- **#6 exp-loop — DONE + on local main (unpushed)** (these sessions follow a commit-directly-to-main pattern; no separate feature branch, 21 ahead of origin/main). What it builds: core `omx_core/loop.py` (`compute_deadline`/`deadline_passed` — pure · time-injected deadline ceiling, caller injects ISO now so it's testable without a wall-clock; `queue_pending_launch`/`read_pending_launch` — `runs/<id>/pending-launch.json` atomic write, status='pending approval', corrupt-JSON loud-fail) + `omx_paths.pending_launch_json(run_id)` getter (the only new path) + `omx queue-launch` (queues after injecting a real clock, **never launches**) / `omx loop-status` (calls compute_deadline via `--max-runtime` to report deadline_passed + pending_launch JSON; explicit `--deadline` takes priority) CLI verbs + `omx_core` export. `skills/exp-loop/SKILL.md` (analyze[exp-analyze]→design[exp-design]→eval[omx eval]→keep/discard[decision]→log[ledger]→queue-launch→stop/repeat orchestrator; the "leave-work toggle" deadline gates only analyze/design/eval; training launch is only queued as pending-approval via `omx queue-launch`, **auto-fire absolutely forbidden** D4/B8; keep/discard target = surface the config git-revert command (no auto-exec) + checkpoint pointer B6; no-max-runtime defaults safely to a single pass). **0 new training launches, the NaN guard was already handled in #3 (not work here).** **314 passed / 1 skipped.** Each task passed spec+quality 2-stage review (T3 corrupt-JSON test, T5 loud-fail try-block, T6 deadline-compute gap = a real defect the review caught, fixed). plugin.json skills = [exp-init, exp-analyze, exp-design, exp-loop] **4 complete**. NEXT = **#7 finalize** (omha card + claudebase registration; **`git pull` required before claudebase registration** — user instruction, memory `claudebase-pull-before-register`).

- **#8 workspace-wiki — DONE + on local main (unpushed)** (2026-05-31). Core
  `omx_core/wiki/{types,storage,ingest,query,lint}.py` (OMC wiki re-implemented in
  Python, Claude-free, time-injected) + `omx wiki add/query/lint/list` verbs +
  `omx_paths` wiki getters (finding/registry_index removed) + the 4 skills wired
  (exp-init seed / exp-analyze query+add via --from-report / exp-design query /
  exp-loop lint report-only). NO new skill (plugin.json stays 4). INV-1 generality
  (zero domain terms in core) + INV-2 compounding (append-only merge, CJK-bigram
  Korean search) held. Spec `docs/superpowers/specs/2026-05-31-omx-workspace-wiki-design.md`,
  plan `docs/superpowers/plans/2026-05-31-omx-workspace-wiki.md`. Suite 365 passed,
  1 skipped. NEXT = #7 finalize (deploy; claudebase pull-first).

- **#3 exp-init — DONE** (branch `feat/omx-exp-init`, not merged · not pushed). What it builds: `omx_core/profile.py` (`validate_metrics_schema` loud-fail validation + `bootstrap_profile` atomic 4-file write + `default_metrics`) + `omx init` CLI verb (thin entry to profile.bootstrap, rc 0/2) + `skills/exp-init/SKILL.md` (re-implements the deep-interview 3-dim gate: Goal 0.40/Criteria 0.30/Constraints 0.30, threshold 0.2; 5-topic→3-dim mapping §4.1; prose numbered options instead of AskUserQuestion; `omx init` handoff + pending-approval hard gate) + plugin.json registration. **Side fix**: `main()` surfaces string-coded SystemExit messages to stderr (previously rc=2 lost the message — a loud-fail violation, found in the build #3 review). **252 passed / 1 skipped.** Each task passed spec+quality 2-stage review. NEXT = #4 exp-analyze (PNG-vision, real WandB/TB adapters; activates the profile's vocabulary tier).
  - Note: the line 17 "handle `_cmd_eval` allow_nan=False in #3" Minor is already resolved (`allow_nan=False` went into `_cmd_eval` in `2191736`). That item is stale.

### #1 Minors left by opus (all polish, not applied — intentional)
M1 csv/eval float() errors lack row/file context (already loud-fail) · M2 session-id second-granularity (pid is enough) · M3 plot docstring "cap" is approximate under tight-bbox · M4 no dep upper bound (normal for a research tool). All future-hardening, not blockers.

## Environment Pitfalls (already got burned by these)
- `python` = the Isaac Sim wrapper. **Always use `python3`** (3.12.3 + pytest 9.0.2).
- `pip install -e .` hits PEP 668 → needs `--break-system-packages` (root Docker, safe).
- Pyright `reportMissingImports` (omx_core.*) + summarize.py `.rename` ndarray warning = editable/pandas-stub false positives — ignore.
- Deploy dir = `omx-core/` (hyphen), import package = `omx_core/` (underscore). cache = `.npz` (not parquet).
- Tool output often renders one turn late / all at once (transport delay, not state corruption). cwd gets polluted by relative-path re-entry after `cd omx-core`, so use absolute paths or cd to repo-root.
- `AskUserQuestion` fails in this environment due to a missing guard hook → decisions are replaced with a prose recommendation + proceed.

## subagent-driven execution pattern (verified, reused in #0 · #1)
Per task: fresh implementer (sonnet) → spec review (haiku) → quality review (sonnet) → on pass move to next → when all done, opus final review → finishing-a-development-branch (merge-local, no push).
**Lesson (burned in #1):** when dispatching implementer and reviewer concurrently, don't embed a **guessed SHA** in the reviewer prompt — the real SHA isn't fixed until after the commit (most reviewers recovered it via git log, but 1 misdiagnosed). Confirm the real SHA after the implementer finishes, then dispatch the reviewer. Give the quality review an explicit instruction to check "does the test actually exercise the real code branch" (that's where the dead width-cap test was caught).

## Locked Design Decisions (do not re-litigate — design §0.1)
B1 2-tier validation / B2 session_id (flag→env→autogen) / B3 report.md single persistent-tree home + plot promotion /
B4 DAG (exp-init #3, evaluator #2 = reference profile) / B5 score pass_only-selectable · score_improvement required /
B6 revert = config git + checkpoint pointer / B7 card url declarative / B8 no auto-fire of training launch (queue) / D3 no MCP server.
