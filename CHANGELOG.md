# Changelog

All notable changes to oh-my-experiments are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/), and the
project adheres to semantic versioning on the plugin (`.claude-plugin/plugin.json`).

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
