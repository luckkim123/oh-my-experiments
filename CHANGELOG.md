# Changelog

All notable changes to oh-my-experiments are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/), and the
project adheres to semantic versioning on the plugin (`.claude-plugin/plugin.json`).

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
