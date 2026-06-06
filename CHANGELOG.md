# Changelog

All notable changes to oh-my-experiments are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/), and the
project adheres to semantic versioning on the plugin (`.claude-plugin/plugin.json`).

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
