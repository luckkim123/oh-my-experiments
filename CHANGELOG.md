# Changelog

All notable changes to oh-my-experiments are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/), and the
project adheres to semantic versioning on the plugin (`.claude-plugin/plugin.json`).

## [0.3.0] - 2026-07-06 — R2: tree governance

### Added

- **tree.yaml typed-section schema + 5 tree verbs.** `tree-codify`/`tree-audit`/
  `tree-scaffold`/`tree-alias`/`tree-index` give the output-tree layout a declared,
  machine-checkable schema instead of prose convention: codify infers `tree.yaml` from
  a census of an existing tree (pending approval), audit validates the tree against it
  (report-only, `--strict` escalates to rc 2), scaffold mints a run skeleton or eval
  leaf per the schema (refuses existing leaves), alias creates/re-points a declared
  symlink atomically, and index regenerates a marker-guarded `INDEX.md`.
- **`omx clean` (#22).** Review-gated `.omx` cleanup: classify → dry-run → `--apply`
  moves candidates to `.omx/.trash` (never `rm`; output trees stay structurally
  unreachable), with `--scope {session,run,all}`, `--older-than`, and a
  `--purge-trash --i-understand-permanent` path for the one irreversible step.
- **Root resolution ladder (#13).** Every verb's `--root` is now optional: absent, it
  resolves via `OMX_STATE_DIR` → `.omx-workspace` marker → cwd search, with
  `OMX_NO_ROOT_LADDER` to opt out and force explicit `--root`.
- **Campaign ledger + 4 verbs (#28).** `campaign-init`/`campaign-log`/`campaign-status`/
  `campaign-list` track a multi-run campaign's plan and event history (launched/kept/
  discarded/eval/note) under `.omx/campaigns/<id>/`, keyed by the tree's group segment.
- **`probe-novelty` ledger scan.** Extends the existing wiki+proposals novelty check to
  also scan campaign and run ledgers for prior outcomes on the same probe family.
- **Skill-to-CLI contract test (#25).** A test asserting every CLI verb a skill's
  markdown names is a verb the parser actually registers, so a skill can no longer
  drift ahead of (or behind) the CLI.
- **Distribution-axiom test (D12).** Mechanizes the "no per-workspace identifier ships
  in core" rule as a pytest guard over checked-in prose (README/CHANGELOG/skills/docs),
  rather than leaving it as an unenforced convention.

### Changed

- **`--root` optional everywhere.** Default = the resolution ladder; implicit callers
  that used to require an explicit `--root` now resolve one — previously some verbs
  either errored or silently skipped profile lookups without one.
- **`omx doctor`** reports `resolved_root`/`root_stage`/`tree_yaml_present` and computes
  `profile_present` against the resolved root (not a hardcoded path).
- **`wiki lint`** honors the profile's `wiki_quality_floor` override (M-4) instead of a
  single hardcoded threshold.
- **`probe-novelty --path`** is now the canonical flag; `--proposal` is kept as a
  deprecated alias for backward compatibility (M-6).
- **`omx init`** additionally writes the default `tree.yaml` when one is absent.
- **`wiki sync-profile`** projects `tree.yaml` into the reserved `profile.md` view, and
  re-syncs correctly on same-second mtime ties (previously a same-second write could be
  skipped as apparently up to date).

### Fixed

- **`run_hook.py` Windows SIGALRM noise (M-5).** The hook runner no longer emits a
  spurious warning on platforms without `SIGALRM`.
- **5 workspace-identifier leaks in shipped prose (D12).** Removed forbidden
  per-workspace identifiers from checked-in docs/skills text, now guarded by the new
  distribution-axiom test.
- **`tree-codify` no longer descends into a detected run (final-review MUST-FIX F1).**
  Its run-candidate walker was missing the "never descend into a detected run" guard
  that `tree.py::walk_runs` already had, so a run's own `analysis/<sub>/manifest.json`
  (e.g. an exp-analyze diagnose report) was miscounted as a deeper run, inflating the
  depth census. The walker now shares the same non-descent guard.
- **`tree-codify` flags un-inferred `data.levels` (final-review MUST-FIX F2).** Codify
  always emitted `data: {levels: []}` with no signal that the levels were never
  inferred, so the first `tree-audit` on a nested data/log tree could false-positive
  an "unindexed run". Codify now surfaces a `data_levels` report hint and a review
  comment in the generated `tree.yaml` telling the reviewer to fill it in.

### Notes / spec deviations

- `tree-scaffold --under` replaces the spec's illustrative `--exp`/`--group` flags:
  level *names* are per-workspace instance data, and D12 forbids baking per-level flag
  names into core.
- The sync-profile same-second fix uses a strict-inequality mtime skip instead of
  compose-and-compare, because the projection embeds its own regeneration timestamp
  (the up-to-date guarantee is unchanged, just the check is cheaper).
- Wiki grammar v1 documents a dash-only-label limitation: an underscore-label writer
  only weakens tag-presence checks, not correctness.

## [0.2.0] - 2026-07-06 — R1: precision core + minimal gates

A structural gap between what exp-analyze/exp-design *specified* and what the harness
could actually *enforce*: gates existed only as skill-level prose, so a report could be
hand-edited after the fact, an evaluator script could be swapped between approval and
launch, and wiki knowledge could accrete without any quality signal. R1 closes this
along two axes: enforcement (make the existing guarantees loud-fail and, where useful,
un-skippable) and rigor (give the harness the quality/novelty/version signals it was
missing). Every new guarantee is carried by a CLI verb loud-fail first; hooks are a
fail-open convenience layer on top (D9), never the sole enforcement point.

### Added

- **Hook runner + report-guard.** A fail-open `hooks/run_hook.py` dispatcher (spec 3.1,
  OMC `run.cjs` pattern in Python) wired as a `PreToolUse` hook on `Edit|Write`, with a
  `report_guard` handler that blocks hand-editing a gated `report.md`/`report.ko.md`
  once it exists (spec 3.2) — the incident class the 0.1.14 entry recorded, now
  structurally blocked at the edit call instead of relying on the skill remembering
  the rule. `OMX_DISABLE=1` and `OMX_SKIP_HOOKS=<names>` kill switches.
- **Integrity stamp + verify chain.** `report-coverage` now stamps a sibling
  `manifest.json` (sha256 + gate summary) on a passing report (#14); `report-verify`
  recomputes the hash and rc-2 fails on any deviation (strict); `report-parse` (the
  consumer boundary) warns on unstamped legacy reports and rc-2 fails on hash mismatch
  or missing gates, reconciling strict-verb vs backward-compat per spec 3.3/4.
- **`report-review` verb + `report-reviewer` agent.** A deterministic critic checklist
  (spec 3.4) plus a read-only `report-reviewer` agent (author != reviewer) that runs the
  mechanical layer first, then judges what code cannot (evidence-to-claim correspondence,
  earned-vs-asserted confidence, narrative consistency). Per spec 3.4, R1 *records* the
  verdict (`review.json`) and never sets an exit code — exp-analyze applies revisions
  through the existing RE-analysis path.
- **`profile-seal` verb + eval preflight.** Seals `.omx/profile/{evaluator.sh,launch.sh}`
  sha256 at approval time (#0); `omx eval --root` checks the seal before running and
  warns (never hard-fails in R1) on drift or a missing seal — reviewer-fixed contract:
  optional `--root`, files not commands, absent-seal/no-root both warn (spec 3.5).
- **Wiki quality gate, `capture-session`, `sync-profile`, lint a-3.** A numeric quality
  score with a profile-overridable floor (force-low below it) surfaces at `wiki add`
  time (#3); `wiki capture-session` writes every report `[FINDING]` as a low-confidence
  session-log stub automatically (#11); `wiki sync-profile` regenerates a reserved
  `profile.md` projection from `.omx/profile/` (#17); `wiki lint` gained a-3
  (high/low confidence mix on a shared tag, #23) alongside the existing lint families.
- **`proposal-lint` + `probe-novelty`.** `proposal-lint` gates exp-design proposals for
  H1/H2 discriminating predictions plus evidence and references (loud-fail, spec 3.10);
  `probe-novelty` warns (never blocks) when a proposed probe family was already tried,
  checked against both the wiki and past `proposals/<id>.md` files.
- **Bounded ingest.** Ingest paths gained explicit limits (flags plus a profile
  `ingest_limits` override) so an unbounded TensorBoard/scalar read can no longer run
  the process out of memory — every new threshold in this release has an override
  (D12): ingest via flags/profile, wiki quality via `wiki_quality_floor`, hook timeout
  is internal-only.
- **`sync_version.py` + `omx doctor`.** `scripts/sync_version.py` fans the
  `.claude-plugin/plugin.json` version (the SSOT) out to `omx-core/pyproject.toml`
  (#6); `omx doctor` is a read-only environment preflight covering install, deps,
  profile presence, and hooks presence (#19).

### Changed

- **`report-coverage` stamps the sibling manifest** as part of its existing pass path
  (see Integrity above), rather than coverage being a standalone check.
- **`eval` and `ingest` verbs gained flags**: `eval --root` (enables the profile-seal
  preflight, #0) and the ingest bounding flags above.
- **Skill wiring**: `exp-analyze` now dispatches the `report-reviewer` agent after
  coverage gates pass; `exp-analyze`/`exp-loop` call `wiki capture-session` at
  iteration end; `exp-design` runs `proposal-lint`/`probe-novelty` before a proposal
  is considered ready for approval.
- **`omx-core/pyproject.toml` version** now follows `.claude-plugin/plugin.json` via
  `sync_version.py` instead of being hand-maintained (drift source for the version
  fan-out gap this release closes).

### Verification

- omx-core full pytest suite green: 586 passed / 1 pre-existing skip (baseline before
  this task's edits was already at this count — the version bump/CHANGELOG/README
  changes in this release commit carry no test-affecting code).
- `python3 scripts/sync_version.py` fans `0.2.0` from `plugin.json` to
  `omx-core/pyproject.toml`; `test_version_sync.py` asserts the two stay in sync so
  drift fails pytest going forward.

### Notes

- **Hooks require a plugin reinstall to activate.** The `PreToolUse` `report_guard`
  hook is inert until the plugin is reinstalled from this version — update the
  claudebase installer (D7) as part of publishing this release so downstream
  installs pick it up.
- **Backward compat.** Unstamped legacy reports (pre-0.2.0) warn rather than fail in
  `report-parse`; a strict rc-2 fail on `unstamped` is deferred to 0.3.0 (rc2). An
  absent evaluator/launch seal warns in this release; hard-fail is a later milestone.
  No retroactive quality scoring is applied to pre-existing wiki pages.

## [0.1.14] - 2026-06-14

A structural hole in the exp-analyze deliverable, surfaced by an incident where a
session patched a `report.md` section by hand (a wall-of-text paragraph with 3+
numbers run inline and no evidence tags) while every sibling section was tables +
short noun-phrases. The format gates were already specified in the skill — D1
(`:151`), the mandatory evidence tags (`:142`), the PRE-WRITE table-of-contents
gate, and the `omx report-coverage` lint — but they ALL fire only on the skill's own
`atomic_path` write path. Opening the file with the Edit/Write tool and patching a
section directly bypasses every one of them at once, and the coverage lint cannot
recover the miss because it counts tokens, not visual format (a wall-of-text
paragraph with the right tokens passes the lint, verified).

### Added

- **exp-analyze: "NEVER hand-Edit report.md" rule.** Once a `report.md`/`report.ko.md`
  exists, it may not be modified with the Edit/Write tool — any change (a finding, a
  number, an augmentation, a one-line fix) is a RE-analysis: re-enter the skill, take
  the OLD report as the BASE, and rewrite through the `atomic_path` writer so all gates
  run. Binds even for one-liners (the exact shape of the incident). Cross-referenced
  from the RE-analysis section and the "When done" gate list.
- **exp-analyze: format self-check before the atomic write.** A 3-point self-check the
  author runs on every added/changed paragraph BEFORE writing — (1) 3+ numbers /
  multi-axis comparison rendered as a bullet list or table, not a run-on sentence
  (D1); (2) every new finding carries its `[FINDING]`/`[EVIDENCE]`/`[CONFIDENCE]` tags;
  (3) visual consistency with the sibling sections. This is the authoring counterpart
  of the coverage lint: the lint is the structural backstop, the self-check is the
  format/evidence gate the lint structurally cannot be.

## [0.1.13] - 2026-06-14

A discoverability gap, surfaced by the same OMC-vs-omx wiki comparison that drove
0.1.12: a session reading only the project rules or `omx wiki --help` wrongly
concluded "delete does not exist". omx has no `delete` subcommand by design (`add`
is append-merge — INV-2; removal is the git-guarded two-phase `gc`/`gc-apply` path),
but nothing made that path findable from `--help`, and `lint` could not catch the
duplicate pages the missing-delete confusion left behind.

### Added

- **Near-duplicate lint.** `wiki lint` now emits `near-duplicate` (info) for page
  pairs whose title-derived slug tokens overlap at Jaccard `>= 0.5`. Catches the
  slug-fork failure mode — the same knowledge re-added under an evolved title forks
  the slug instead of merging. No embeddings (hard constraint), pure lexical overlap.
  Same signal-only, candidate-not-verdict shape as `contradiction-candidate` (INV-1).
  The 0.5 threshold (not 0.6) accounts for the 64-char slug truncation that gives an
  evolved-title duplicate divergent tail-noise tokens; the real on-disk pair
  `engine_gap_eval_adapter_*` shares 7 content tokens yet scores 0.583.

### Changed

- **`gc`/`gc-apply` help now names the delete/merge path.** `omx wiki --help` states
  that `gc-apply` IS how you delete/merge pages and that there is no separate `delete`
  subcommand by design — so the confusion above resolves from `--help` alone.

## [0.1.12] - 2026-06-08

The last OMC lint check that omx was missing (from the same wiki source
comparison): a `low-confidence` signal. Closes the lint-parity gap; all other
OMC wiki features are either deliberately not ported (session hooks — omx is a
CLI, no lifecycle to fire on) or already matched/surpassed (omx's git-guarded gc,
loud-fail, injected-now). `wiki_add` (reject-on-duplicate) is intentionally not
ported — it conflicts with omx's always-append-merge compounding model.

### Added

- **Low-confidence lint.** `wiki lint` now emits `low-confidence` (info) for any
  page whose `confidence` is `'low'`, flagging it for review/strengthening. Same
  signal-only, candidate-not-verdict shape as `contradiction-candidate` (INV-1).
  exp-loop §6's report list includes it; the lint module docstring is corrected
  (orphan definition updated to `inbound==0`, the full current type list enumerated).

### Verification

- omx-core full pytest suite green (498 passed / 1 skipped); +2 wiki test
  functions (one positive, one high/medium negative). ruff clean on lint.py.
- Separate-lane code review (feature-dev:code-reviewer) confirmed INV-1 intact
  and no invariant regression, verdict APPROVE.

## [0.1.11] - 2026-06-08

Four wiki-lint enhancements from an OMC-vs-OMX wiki source comparison, each
re-shaped to OMX purpose (INV-1 candidates-only, loud-fail, injected-now, no
auto-delete all preserved).

### Added

- **Contradiction-candidate lint.** `wiki lint` now emits `contradiction-candidate`
  (info) signals: >=2 high-confidence pages sharing a tag, or a tag spanning
  multiple categories. Structural candidates for human review only — the core never
  judges whether content actually conflicts (INV-1).
- **lint -> gc suggestion pipe.** `wiki gc` diagnosis now includes a `suggestions`
  block: orphan slugs pre-formatted as a ready-to-edit `wiki-gc` proposal skeleton,
  so cleanup no longer means hand-transcribing slugs. Review-only; `gc-apply`
  (git-guarded two-phase) stays the sole executor. stale is excluded by design
  (old != useless for experiment knowledge).

### Changed

- **Stronger orphan definition.** `orphan` is now `inbound == 0` (nobody links to
  the page), catching dead-end pages that link out but are never linked to —
  previously a page was orphan only with no links in EITHER direction. New seed
  pages (created within `stale_days/2` of now) are exempt to avoid flagging
  still-growing knowledge.
- **exp-loop wiki reminder.** The iteration-end wiki audit now also reports
  `orphan` / `contradiction-candidate` and, when info+ issues accumulate, reminds
  the user to run `omx wiki gc` for delete candidates. Surface-only.

### Verification

- omx-core full pytest suite green (496 passed / 1 skipped); +7 net wiki test
  functions.
- CLI smoke: `omx wiki gc` emits a valid `suggestions.proposal_skeleton`.
- Separate-lane code review (feature-dev:code-reviewer) confirmed INV-1 /
  loud-fail / injected-now / no-auto-delete intact, verdict APPROVE.

### Notes

- Source analysis recorded in `claudebase/docs/reference/omc-wiki-skill-analysis.md`.
- Design + plan: `docs/superpowers/specs|plans/2026-06-08-omx-wiki-lint-enhancements*`.
- The orphan-definition change is the only intentional behavior change (one existing
  test rewritten accordingly).

## [0.1.10] - 2026-06-08

Two exp-analyze report-quality gates from the dr_harder 2026-06-08 incidents,
built as a stack on `report-coverage`. They guard ORTHOGONAL failure modes: a
re-analysis that shrinks (depth), and a carried-forward cross-run reference value
that goes stale (value freshness) — a report can pass one and fail the other.
Both are generic: no domain tokens in core, all sections/refs caller-supplied.

### Added

- **Depth-regression gate — `report-coverage --baseline` + `required_sections`.**
  A re-analysis (re-run because plots/numbers changed) was rewritten from scratch
  off the data pack instead of from the OLD report, coming out 25-39% shorter, with
  the whole `## generalization (OOD)` section deleted — yet it passed the token
  lint because each group token still appeared once. The gate now (a) fails if a
  declared `required_sections` heading is absent (a deleted section the token lint
  cannot see), and (b) with `--baseline <old report | auto>`, fails on a depth
  regression (fewer `[FINDING]`s, fewer data-table rows, or words down past
  tolerance) vs the report it replaces. `--baseline auto` picks the latest sibling
  analysis. exp-analyze SKILL gains the "RE-analysis uses the OLD report as BASE,
  never start short" rule and makes the gate part of When-done.
- **Cross-run reference-value gate — `report-coverage --cross-run-refs`.** The E4
  report carried a `teacher hard` reference column whose value was copied from a
  prior report and went STALE — it no longer matched the canonical teacher eval,
  so "roll/yaw beat the teacher" was a lie the depth gate could not catch (the
  report had GROWN). `check_cross_run_refs(report, refs)` verifies, for each
  caller-supplied `{label, summary_path, field, reported_value}`, BOTH provenance
  (the source eval id — the summary.json parent-dir name — is cited in the report)
  AND value (matches `summary.json[field]` within rounding tolerance). A stale value
  OR an uncited source loud-fails (exit 2). The fragile table-parsing that builds
  the refs is the caller's job; the core only verifies. exp-analyze SKILL gains
  RE-analysis rule 6: carry forward the PROSE, never the cross-run reference VALUES
  — re-extract every cross-run number fresh and cite its source eval id.

### Verification

- 489 pass / 1 skip (16 new tests: 11 unit + 5 CLI for the cross-run gate, plus the
  depth-gate tests), ruff clean. Validated on the real dr_harder E4 report: correct
  teacher value -> pass; injected stale 1.06 (vs file 1.2834) -> STALE fail; E1
  report (teacher column, eval id uncited) -> UNCITED fail.

## [0.1.9] - 2026-06-07

exp-analyze report-format fix: the report must be **bookended**. The PRE-WRITE
gate already forced the diagnostic groups to be the required table of contents,
but nothing forced a top TL;DR or a closing synthesis — so a report could open
with findings and simply trail off on its last diagnostic group, leaving the
reader to synthesize the takeaway themselves. Surfaced reviewing the dr-harder
teacher report (had a TL;DR, no closing verdict). No engine/CLI change.

### Changed

- **exp-analyze PRE-WRITE gate gains step 4 — bookend the group sections.** The
  report now MUST open with a `## TL;DR` (baseline state + the one real weakness +
  the headline metric) and CLOSE with a `## verdict` / `## bottom line` (2–4
  sentences: the single most important takeaway + implication for the next
  experiment). The per-group sections are the evidence body, not a substitute for
  the synthesis. The "When done" backstop now also confirms the bookends.

## [0.1.8] - 2026-06-06

Round-4 CLI honesty fixes: five gaps where the tooling silently swallowed
misuse or a structural limit, surfaced while re-analyzing a teacher run. Same
family as the 0.1.7 chain ("the engine ran" vs "the result is grounded"), now
extended to "the CLI loud-fails on misuse" and "the report lands where it
belongs". All landed test-first; no machine- or project-specific assumptions
(the path fix is documentation-only — the core getter stays general).

### Added

- **`omx plot --format eval_summary --view per_axis_bar`** now renders a real
  per-axis bar PNG (GAP B). The eval_summary adapter is tabular (`series={}`);
  the plot layer now builds the bar chart directly from `SummaryRecord`s, one
  bar per axis for a dr_level. Schema-driven — works for any
  `{dr_level:{axis:{field:value}}}` summary.json, no axis names hardcoded.
- **`partial_groups` in `omx report-coverage`** (GAP E) — lenient mode used to
  pass a group with only 1 of N tokens referenced as `ok:true`, silently
  accepting field-level omissions within a passing group. Coverage now surfaces
  groups with `hits < total` (but `>= required`) as `partial_groups` in the
  JSON output plus a per-group stderr WARNING. `ok` semantics and lenient mode
  are unchanged (advisory only), so an intentionally-N/A whole group is still
  distinct from a contracted field missing.

### Changed

- **`omx reduce summarize --cv-field <x>`** now loud-fails (exit 2 + sorted
  `available:` field list) when the field is not in the ingested record
  vocabulary (GAP A) — previously it returned `{"cv": []}` at exit 0, so an
  axis name like `roll` (instead of a field like `ss_error`) gave a silent
  empty result. An empty summary (0 records) still returns `[]` quietly — a
  genuine data absence is distinguished from a bad field name.
- **exp-analyze SKILL** gains three guidance rules (GAP C + D), documentation
  only, no code: (C) the "Grouped runs" box now states the group MUST carry all
  path segments between `output_root` and `run_id` — for RSL-RL runs the
  framework subdir too (`rsl_rl/<exp>/<purpose>`), since omitting it silently
  drops the report into a sibling tree; (D1) an `[EVIDENCE]` block with 3+
  numbers or a multi-axis × DR comparison must use a bullet list or table, not
  a wall paragraph; (D2) `report.md` contains only this run's analysis —
  harness/engine-gap metadata and CLI-misuse notes go to the wiki + fix-prompt,
  not the report body.

### Verification

- Full suite: 462 passed, 1 skipped (was 451; +5 GAP A/B tests, +6 GAP E
  tests). No new ruff violations in changed files (a pre-existing F401 in
  `reduce/summarize.py` is untouched, out of scope).
- Deployment generality preserved: core changes confined to `cli.py` and
  `coverage.py`; the `omx_paths` getter and the `EvalSummaryAdapter` are
  unchanged, so no workspace-specific path or field name leaks into the
  distributed core.

### Notes

- Delivered via a `team` (native-agents) workflow: the lead session planned,
  reviewed, and merged; two isolated workers fixed on separate branches
  (GAP A–D in the main tree, GAP E in a git worktree) — branch conflicts made
  structurally impossible rather than negotiated. Merged via two `--no-ff`
  commits.

## [0.1.7] - 2026-06-06

Three exp-analyze reliability fixes plus a wiki garbage-collection workflow,
all landed test-first. The three fixes form one chain: they harden the path
from "the engine ran" to "the report is actually grounded", each closing a
hole that let a thin/empty dr-harder report pass three times in a row. The
wiki-gc workflow is an independent feature (consolidating an accreted wiki),
integrated in the same release. No machine- or project-specific assumptions.

### Added

- **`omx reduce tb-final`** — named final-window means for a list of TB tags.
  exp-analyze could run the diagnostic engine but had no first-class verb to
  pull a *specific* scalar's final-window value when the engine left a cell
  empty. `final_window_means(series, tags, window)` returns the trailing-window
  mean per tag and **loud-fails** (never silent 0) on an absent tag (listing the
  available scalar tags), a zero-sample tag, or a `_step/`-prefixed index key.
  This is the extraction half of the engine-output cross-check (below).
- **`omx report-coverage`** lint — catches a report that skipped a whole
  diagnostic group or never cited the engine. Reads the profile's optional
  `groups` (group -> metrics) and `engine_markers`, prints per-group
  `group_hits` (hit/total), and loud-fails on an under-covered group or a
  missing engine marker. A new opt-in `--min-coverage <frac>` strict mode
  (default lenient = back-compat) requires `max(1, ceil(total*frac))` tokens
  per group, so a group named only once when it has several metrics is caught
  — not just a group skipped entirely.
- **`omx wiki gc` / `omx wiki gc-apply`** — a human-gated wiki garbage-collection
  flow. `gc` is read-only: returns the lint plus a page inventory
  (`slug/title/category/updated/bytes`) so you can spot overlapping or
  superseded pages. You write a `kind: wiki-gc` proposal (DELETE / MERGE
  sections, one reason per line); the user edits it (editing IS the approval);
  `gc-apply` runs two-phase — validate the whole proposal (slugs exist,
  git-tracked, no self-merge) then execute under the wiki lock. It **refuses to
  touch any page git does not track** (so `git restore` always recovers) and
  does not commit (you commit after review). Merges are lossless append-merges.

### Fixed

- **Engine output accepted unverified** (dr-harder fix #2). exp-analyze ran the
  engine, saw an empty/0 cell (e.g. `constraints=0`, an empty reward-decomp
  table), and copied it into the report as fact. Two root causes: (a) the
  workspace engine's constraint discovery only knew the legacy
  `Constraint/cost_return_*` naming and missed this repo's `margin/<name>` +
  `viol/<name>` tags, so a run with 10 live constraints reported 0; (b) the
  skill had no rule forcing a raw-TB cross-check. Fixed both: the profile
  adapter now discovers both namings (verified on a real run: `constraints=10`
  with a margin/viol table), and the skill now mandates — *an empty cell is a
  HYPOTHESIS ("the tool didn't find the tag"), not a fact ("no data")*: dump
  `ea.Tags()['scalars']`, and if the tag exists, extract it via
  `omx reduce tb-final` rather than reporting empty.
- **Multi-line `[FINDING]` claims silently dropped** (dr-harder fix #1).
  `report.parse_findings` only matched single-line findings, so a wrapped
  claim was lost from the coverage accounting. Now parses multi-line findings.

### Changed

- **Completeness is now a PRE-WRITE gate, not a post-hoc audit** (dr-harder
  fix #3). The earlier coverage lint ran only *after* the report was written,
  by which point the agent had already convinced itself it was done — it caught
  nothing three times running. The exp-analyze skill now derives the required
  per-group table of contents from the profile's `groups` into a PRE-WRITE
  TodoWrite checklist ("groups ARE the required ToC, decided before a single
  sentence"); the strict `report-coverage --min-coverage 0.5` lint is recast as
  the backstop, and the "When done" step must prove the strict lint returned
  `ok: true` before declaring done. A group may be marked N/A only after the
  raw-TB cross-check above — "the engine reported it empty" is no longer a
  valid reason to skip a group.

## [0.1.6] - 2026-06-06

Two CLI interface fixes, each landed test-first (failing reproduction test ->
fix -> green). Both are general-distribution fixes (no machine- or project-
specific assumptions).

### Fixed

- **`omx session-id` argless crash** (`'str' object is not callable`). When
  neither `--session-id` nor `OMX_SESSION_ID` was set, the autogen fallback
  advertised by the exp-analyze skill blew up: `_cmd_session_id` passed the
  autogen *value* as a string, but `resolve_session_id` expects a zero-arg
  *callable* (kept injectable so the core stays pure / deterministically
  testable). Fix wraps it in a lambda at the one call site (`cli.py`); the core
  contract is unchanged. The explicit-flag and env paths were never affected, so
  the regression lived solely in the autogen branch — now covered by a test
  (`test_session_id_autogen_when_no_flag_or_env`) that the prior flag/env tests
  could not reach (they always set the env).

### Added

- **`omx wiki read --slug <slug>`** verb. The wiki had `{add, query, lint,
  list}` but no first-class way to pull a page's *full* text once you know its
  slug — `query` returns only truncated snippets, forcing a hand-Read of the
  `registry/findings/<slug>.md` path (hard-coded, bypassing the omx_paths
  getters). `read` resolves the path through `storage.read_page` and prints the
  whole page (frontmatter + body via `serialize_page`); `--no-frontmatter`
  emits the body only. An absent slug loud-fails (non-zero exit, empty stdout)
  so a caller can tell "page absent" from "page empty". This completes the
  exp-analyze "Ground in prior workspace knowledge" path (query to find,
  read to pull). Symmetric with `list`/`add` (query = search, read = full text).
