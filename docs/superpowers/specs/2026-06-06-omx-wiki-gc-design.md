# omx wiki gc — restructure / consolidate / stale-cleanup (design)

> Status: approved design (brainstorming complete), ready for writing-plans.
> Date: 2026-06-06. Target repo: `~/oh-my-experiments` (omx-core CLI).
> Prior art: `docs/superpowers/specs/2026-05-31-omx-workspace-wiki-design.md` (the wiki itself).

## Problem

The omx wiki accrues knowledge but has no maintenance path. On the one live wiki
(`constrained-albc/.omx`, 19 pages) a real `omx wiki lint --root .` shows the
actual pain:

- **12 of 19 pages are orphans (63%)** — no inbound or outbound links.
- **0 stale, 0 broken-ref, 0 oversized** — nothing is old enough (< 30 days) or
  over the 10 KB cap (largest page 7.7 KB).
- **Semantic duplicate clusters that lint cannot see**, e.g. two `engine-gap eval
  adapter` pages where the later one ("covers static + segmented") supersedes the
  earlier ("only covers static"); three `teacher hard-DR` pages that are facets of
  one phenomenon.

So the wiki needs two things lint does not provide: a way to **delete** superseded
/ stale pages and a way to **merge** semantically-overlapping pages — both
destructive (information can be lost), so both require a human gate and a recovery
path.

## Settled scope (from brainstorming)

| Decision | Choice |
|:---|:---|
| Automation boundary | **lossless = automatic, lossy = human-approved**. The axis is *information loss*, not *risk feel*. |
| What lint already covers | lossless diagnosis (orphan / stale / broken-ref / oversized, report-only) — **reused, not rebuilt**. |
| New scope this feature adds | **lossy only: page delete + page merge, as a proposal** (semantic judgment). |
| Out of scope | orphan auto-linking (separate lossless work), standalone stale-purge (0 stale today). |
| Who decides what to delete/merge | **the skill (Claude)** reads page bodies; the core never judges. |
| Recovery path | **git** — `gc-apply` refuses to touch any page not tracked by git, so `git restore` always recovers. |
| Apply mechanism | edit the proposal file (deleting a line drops that item) → `omx wiki gc-apply --proposal <file>`. |

## Architecture — core mechanism vs skill judgment

```
+- skill lane (Claude judgment) ------------------------------------+
|  1. omx wiki gc --root <r>  -> JSON {lint issues + page metadata}  |
|  2. read each candidate page body via  omx wiki read              |
|  3. judge semantic duplicates / supersession -> write proposal    |
|     proposals/<ts>-wiki-gc.md  (structured DELETE / MERGE items)   |
|  4. [HUMAN GATE] user reviews proposal, deletes/edits lines        |
+-------------------------------------------------------------------+
                          | approved proposal
                          v
+- core lane (mechanism, ZERO domain knowledge) -------------------+
|  5. omx wiki gc-apply --proposal <file> --root <r>                |
|     -> phase 1 VALIDATE everything (slugs exist, git-tracked,     |
|        no self-merge); any failure -> loud-fail, 0 applied        |
|     -> phase 2 with_wiki_lock:                                    |
|         delete_page(slug)       : unlink                          |
|         merge_pages(from, into) : append-merge into, unlink from  |
|        update_index ; append_log("gc-apply", ...)                 |
+-------------------------------------------------------------------+
```

### Responsibility boundary (the core of the design)

| Work | Who | Rationale |
|:---|:---|:---|
| Mechanical signals (orphan / stale / oversized) | core `lint` (existing) | links / dates / size need no domain knowledge |
| Page metadata + lint folded into one JSON | core `gc` (new, **read-only**) | one-shot input for the skill |
| "these two engine-gap pages are one topic" | **skill** | requires reading content — LLM work, INV-1 |
| Proposal authoring + human gate | **skill** | the product of judgment |
| Safe execution of approved delete/merge | core `gc-apply` (new, **write**) | lock / index / log / git = mechanism |

### Invariants

- The core never decides *what* to delete — `gc-apply` executes an
  already-approved proposal file; `gc` is read-only (zero destruction).
- Every write goes through `with_wiki_lock` -> `update_index` -> `append_log`
  (storage's existing contract, unchanged).
- `gc-apply` checks git tracking *before* any mutation; if `.omx` is not a git
  repo or a target is untracked, it loud-fails and touches nothing.

## Proposal format (the skill <-> core contract)

```markdown
---
kind: wiki-gc
generated: 2026-06-06T10:30:00
root: .
---

## DELETE

- slug: old_engine_gap_only_covers_static.md
  reason: superseded by engine_gap_..._static_segmented (later update, same topic)

## MERGE

- into: teacher_hard_dr_cv_explodes.md
  from:
    - teacher_cross_axis_correlation_collapses.md
    - teacher_segmented_post_switch_roll.md
  reason: three facets of one teacher hard-DR phenomenon
```

**Parse rules (core, Claude-free):**

- frontmatter `kind: wiki-gc` or loud-fail (guards against pointing at the wrong file).
- Two sections `## DELETE` / `## MERGE`; each item carries slugs. **Deleting a line
  drops that item** — editing IS approval.
- `merge.into` is the survivor; `from` pages are merged then deleted. `into` inside
  `from` -> loud-fail (self-merge guard).
- A slug that does not exist -> loud-fail (proposal is stale).
- Empty proposal (0 items in both) -> no-op, exit 0.

**Merge semantics (reuses ingest's append-merge, INV-2 lossless):** `merge_pages`
appends each `from` page's content into `into` as a `## Merged from <slug> (<ts>)`
section, unions tags, appends sources, unions links, takes max confidence, then
deletes the `from` pages. No knowledge is lost in a merge.

## Safety, failure modes, recovery

### git-tracking check (the recovery guarantee)

`gc-apply` confirms two things *before* mutating, and on any failure touches nothing:

1. `.omx/registry/findings/` is inside a git repo and the target slugs are tracked
   — `git -C <root> rev-parse` + `git ls-files`.
2. The check is done by the core via `subprocess`. No git / untracked ->
   `OmxError("wiki gc-apply requires git tracking for recovery; <slug> is untracked")`.

This makes "deleted with no recovery" structurally impossible. The core does **not**
commit — it only executes; committing is the user's / skill's job. Git tracking is
forced so `git restore` can always undo.

### Failure-mode table (all loud-fail, no partial apply)

| Situation | Core behavior |
|:---|:---|
| proposal frontmatter `kind != wiki-gc` | loud-fail, nothing touched |
| proposal slug absent | loud-fail (stale proposal), 0 applied |
| `merge.into` listed in `from` | loud-fail (self-merge) |
| target git-untracked | loud-fail (no recovery) |
| lock acquisition fails (other session) | loud-fail (existing `with_wiki_lock`) |
| empty proposal | no-op, exit 0 |
| some item fails mid-apply | **validate-all-first, then execute** — impossible to half-apply |

### Two-phase apply

1. **Validate** the whole proposal (every slug exists, git-tracked, no self-merge)
   — any failure aborts with 0 applied.
2. Only if all pass: take the lock and execute. "Delete half then die" cannot happen.

## Components & files

New core module `omx_core/wiki/gc.py`:

- `parse_gc_proposal(raw: str) -> GcPlan` — pure parser; loud-fail on bad kind /
  malformed item. `GcPlan = {deletes: [slug], merges: [{into, from:[slug]}]}`.
- `delete_page(paths, slug, *, now)` — git-tracked check -> unlink -> (caller holds lock).
- `merge_pages(paths, *, into, from_slugs, now)` — append-merge into survivor,
  unlink `from` pages (caller holds lock).
- `apply_gc(paths, plan, *, now, git_check=...)` — two-phase: validate all, then
  under `with_wiki_lock` run deletes + merges, then `update_index` + `append_log`.

Reuses from existing storage/ingest: `read_page`, `serialize_page`, `write_page`,
`list_pages`, `update_index`, `append_log`, `with_wiki_lock`, and ingest's
append-merge field logic (tags union / sources append / confidence max).

CLI (`omx_core/cli.py`, same `wsub.add_parser` pattern as `read`):

- `wiki gc --root <r>` -> `_cmd_wiki_gc` — read-only; prints
  `{lint: {...}, pages: [{slug, title, category, updated, bytes}]}` as JSON.
- `wiki gc-apply --proposal <f> --root <r>` -> `_cmd_wiki_gc_apply` — parse,
  two-phase apply, print `{deleted: [...], merged: [...]}`.

Skill guidance: a short section (exp-analyze SKILL.md addition, or a dedicated
note) telling Claude the flow: `gc` -> `read` bodies -> author proposal ->
human gate -> `gc-apply`. The skill does the semantic judgment; the core does the
mechanism.

## Tests (TDD)

- `parse_gc_proposal`: valid / bad-kind / absent-slug / self-merge / empty — pure,
  clock+git injected.
- `delete_page`: git-tracked mock -> unlink + index/log updated; untracked -> loud-fail.
- `merge_pages`: into gains content, tags union, `from` deleted, lossless; into==from -> loud-fail.
- `apply_gc` two-phase: a validation failure leaves disk unchanged (0 partial apply)
  — the most important regression test.
- CLI: `wiki gc` JSON schema; `wiki gc-apply` end-to-end on a `tmp_path` + `git init` repo.
- Prefer a real `git init` tmp repo over mocking `subprocess` (verifies actual tracking).

## Versioning

Two new verbs (`wiki gc`, `wiki gc-apply`) + skill guidance -> **minor bump
0.1.6 -> 0.1.7**. CHANGELOG `Added`. plugin.json version bump.

## Non-goals (YAGNI)

- No heuristic duplicate detection in the core (semantic judgment is the skill's job; a
  title/tag-similarity heuristic would mis-merge "axis decorrelation" vs "CV explodes").
- No orphan auto-linking (separate lossless feature).
- No `.trash/` directory (git is the recovery path; a second mechanism is redundant here).
- No auto-commit by the core (execute-only; commit stays a human/skill decision).
