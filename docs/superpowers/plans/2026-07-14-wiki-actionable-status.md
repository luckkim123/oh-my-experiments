# OMX Wiki Actionable-Status — Execution Plan (TDD)

> **Spec:** `docs/superpowers/specs/2026-07-14-wiki-actionable-status-design.md`
> **Branch:** `exp/wiki-status` · baseline tag `baseline-260714-wiki-status` · target `v0.7.0`
> **Run:** `cd /root/oh-my-experiments/omx-core && python -m pytest -q`
> **Per task:** write the red test → confirm FAIL → implement at the named seam → PASS → full suite → commit.

## Phase 1 — omx

- [ ] **T1 — types + storage round-trip.** `types.py`: `STATUSES = ("needs-experiment",
  "needs-apply-before-retrain", "resolved")`, `BLOCKING_STATUSES = frozenset({"needs-apply-before-retrain"})`,
  `WikiPage.status: str | None = None`, `blocked_on: str | None = None`. `storage.py`: conditional
  serialize (next to the `qualityScore` block) + parse (`fm.get("status") or None`,
  `fm.get("blocked-on") or None`). Tests (`test_wiki_types.py`, `test_wiki_storage.py`): round-trip both
  fields; a status-less page serializes with NO `status:` line; legacy frontmatter parses to
  `status is None`.
- [ ] **T2 — ingest merge + validation.** `ingest_knowledge` gains `status=None, blocked_on=None`;
  unknown status → `WikiError`; create passes through; merge = explicit-wins / None-keeps. Tests
  (`test_wiki_ingest.py`): create-with-status; explicit flip to `resolved`; None-add keeps the flag
  (capture-stub protection); invalid status raises.
- [ ] **T3a — gc merge status carry.** `merge_pages` rank-max status
  (`needs-apply-before-retrain(3) > needs-experiment(2) > resolved(1) > None(0)`) + `blocked_on`
  survivor-first, carried into the merged `WikiPage`. Tests (`test_wiki_gc.py`): blocking source into an
  unflagged survivor → merged blocking; resolved+None → resolved.
- [ ] **T3b — gc quality-drop bug (separate commit).** Same constructor also carries
  `quality_score`/`quality_reasons` (pre-existing silent drop). Test: survivor quality survives a merge.
- [ ] **T4 — surfacing.** `lint.py`: `open-lead` (warning if blocking, info if soft) + `unknown-status`
  (info); `gc.suggest_from_lint` excludes open-lead slugs from `delete_candidates`; `query.py` match
  dict gains `status`. Tests in `test_wiki_lint.py`, `test_wiki_gc.py`, `test_wiki_query.py`.
- [ ] **T5 — enumeration helper + CLI.** `query.enumerate_pages(paths, status=None) -> {pages,
  corrupt_pages}` pure helper; `wiki list --status` filter + `status`/`blocked_on` in output; `wiki add
  --status {…} --blocked-on`. Tests in `test_cli.py`.
- [ ] **T6 — queue-launch gate.** `_cmd_queue_launch`: `enumerate_pages` → partition; REFUSE on
  unacked blocking (`SystemExit`, nothing written); `--ack-gate <slug>` (repeatable) →
  `acknowledged_gates` in the payload; WARN on soft (`open_leads`, rc 0); pass on empty/absent wiki;
  corrupt non-blocking. `loop.queue_pending_launch` optional `open_leads`/`acknowledged_gates`. Tests in
  `test_queue_launch.py` (core + `cli.main`/capsys layers).
- [ ] **T7 — prompt/docs layer (no code).** `hooks/handlers.py` reconcile clause (keep ≤ 2 KiB —
  `test_hook_registration.py` green); `skills/exp-loop/SKILL.md` close-out; `skills/exp-design/SKILL.md`
  wiki-query section; `agents/campaign-auditor.md` dropped-lead + gated-launch bullets. Verify by
  reading + the hook-size test.
- [ ] **T8 — separate-lane code review** (code-reviewer agent; no self-approval). Check INV-1/INV-2,
  injected-now, loud-fail, backwards-compat (no existing test changed).
- [ ] **T9 — release.** `.claude-plugin/plugin.json` 0.6.0 → 0.7.0; prepend `CHANGELOG.md`
  (Added/Changed/Verification/Notes incl. the version-skew caveat); commit; `git checkout main && git
  merge --no-ff exp/wiki-status`; final suite. **STOP — push is user-gated.**

Post-release (content-side, in the `constrained-albc` project, NOT harness work): flag the TAM/IMU pages
+ roster `--status needs-apply-before-retrain` and the backlog lead pages `--status needs-experiment`.

## Phases 2-3 — light harnesses (each after its own `git fetch`; per-harness diff review + version bump)

- [ ] **oms** (`/root/oh-my-scholar`, behind origin — fetch first): `references/wiki/README.md` status
  subsection; `scripts/oms_wiki_audit.py` STATUS_VALUES + unknown-status + open-gap enumeration; TDD via
  `tests/test_oms_wiki_audit.py`; scholar-verify WARN bullet.
- [ ] **omd** (`/root/oh-my-docs` — fetch first): `references/wiki/README.md` subsection; grep
  enumeration; docs-verify/docs-learn WARN step; optional unknown-status check if helpers exist at HEAD.
- [ ] **omp** (`/root/oh-my-project`): reconcile line in omp-brief/omp-handoff; optional derived
  `ready_to_promote` lint finding in `hooks/omp_content_audit.py` (no schema change).

## Self-review checklist (fill at T8)

- Spec-coverage: every §3–§4 decision has a task above.
- INV-1: status values are workflow vocabulary, commented as such in `types.py`.
- INV-2: merge rules cannot silently drop a flag (ingest None-keeps; gc most-open-wins).
- Backwards-compat: no existing test rewritten; a status-less page is byte-identical.
