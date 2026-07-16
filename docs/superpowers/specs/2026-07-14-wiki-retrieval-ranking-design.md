# OMX Wiki Retrieval-Reliability — Ranking + Adoption — Design

> **Date:** 2026-07-14
> **Target version:** v0.7.1 (patch — additive, backwards-compatible)
> **Source tree:** `/root/oh-my-experiments/omx-core/`
> **Depends on:** v0.7.0 (actionable-status convention — already shipped;
> `status`/`blocked_on`, `enumerate_pages`, launch gate, write-time reconcile prose).
> **Scope:** omx is the reference implementation of a convention shared across the om* wiki family.
> **Motivation:** The wiki + reports store experiment knowledge well, but Claude does not reliably
> *retrieve* it at plan/analyze time. Two named sub-gaps remain after v0.7.0: (1) `query_wiki` ranks by
> keyword score alone, so ~65 low-confidence auto-captured session-log stubs rank alongside curated
> pages and bury the high-value ones; (2) ad-hoc planning outside the exp-analyze/exp-design skills is
> not forced to query at all.

---

## 1. The gap + the decision (what this release does and does NOT do)

Storage is not the problem — a top-level `INDEX.md`, group READMEs, 189 wiki pages, and a
report→wiki capture pipeline all already exist and are current. The failure is at **retrieval time**:
what is queried is diluted by noise, and ad-hoc work may skip the query.

**Decision — no per-prompt hook executor.** An earlier option was to make the `route_emit`
UserPromptSubmit hook actually run `omx wiki query` on every prompt and inject the top results. It is
**rejected**: it is paid on every prompt (most are not experiment work), cannot know the query topic
without parsing the prompt, must stay within the 3 s / 2 KiB budget, and directly contradicts the
v0.7.0 design choice of a static, drift-free checkpoint whose procedure bodies live in skills. Instead
this release closes the gap through **better ranking** (so what is queried is good) and **light routing
prose** (so ad-hoc work is nudged into the already-forcing skills), plus a companion **project-adoption**
step (arming the shipped gate). The accepted residual risk is stated in §7.

## 2. Invariants (unchanged from v0.7.0)

- **INV-1 — core carries ZERO domain judgment.** `confidence` and `status` are *workflow* fields
  (the harness's own metadata), not project domain content — weighting by them is a workflow judgment,
  permitted. No project vocabulary (`TAM`, `heavy-tail`, run ids) enters core.
- **INV-2 — append-merge; knowledge accrues without loss.** Ranking is read-only; it never mutates a
  page. No page is dropped or hidden — a down-weighted page still appears if it matches.
- **Backwards compatible.** Ranking is additive: a page with no `confidence`/`status` gets a neutral
  weight, so absent-metadata pages keep surfacing. `schemaVersion` unchanged. No new required field.
- **Loud-fail; visible-skip.** A corrupt page is still visible-skipped into `corrupt_pages`, never
  crashes the query. No wall-clock in scoring (the injected `now` stays log-only).

## 3. Change A — confidence/status-aware ranking (`omx_core/wiki/query.py`)

### 3.1 Current behavior

`query_wiki` (query.py:~129) computes an integer keyword `score` (tag > title > content, OMC weights),
then `matches.sort(key=lambda m: m["score"], reverse=True)`. `confidence` and `status` are returned in
each match dict (v0.7.0) but **never used in scoring**. All pages of equal keyword score tie — a
`confidence: low` auto-stub ranks level with a `confidence: high` curated finding.

### 3.2 Proposed behavior — keyword is the dominant term, metadata breaks near-ties

`weighted = keyword_score * w_confidence * w_status`, sort by `weighted` desc, keyword `score` as the
tie-break. Individual weights are in `[0.70, 1.0]` but the worst-case COMBINED discount is
`low` 0.80 × `resolved` 0.70 = `0.56`, so keyword score is the **dominant** term, NOT strictly primary:
it dominates when scores differ clearly (a `+5` title hit at `low`, `×0.8 = 4.0`, beats a `+1` content
hit at `high`, `×1.0 = 1.0`), while for **near-tied** scores (ratios within ~1.8×) metadata intentionally
re-orders — a `+3` `low`+`resolved` stub (`×0.56 = 1.68`) sinks below a `+2` `high` active page (`= 2.0`).
That near-tie re-ordering IS the stub-sinking feature; strict keyword ordering is mathematically
incompatible with meaningful metadata weighting. **No page is filtered** — only re-ordered (INV-2).

Proposed default weights (module constants, tunable; final values fixed in the plan):

| field | value | weight | rationale |
|:---|:---|:---|:---|
| confidence | high | 1.00 | curated, trust |
| confidence | medium | 0.92 | |
| confidence | low | 0.80 | the auto-captured session-log stubs — sink on ties |
| confidence | None / unknown | 0.90 | neutral fallback; genuine frontmatter-absence loads as `medium` (0.92) per the storage default, so 0.90 is reached only for an explicitly-null or unrecognized value |
| status | needs-experiment / needs-apply-before-retrain | 1.00 | actionable, keep visible |
| status | resolved | 0.70 | settled/historical — mild sink, still surfaces on a strong match |
| status | (absent) | 1.00 | not actionable, no effect |

Weights live as named constants (`_CONFIDENCE_WEIGHT`, `_STATUS_WEIGHT` dicts) next to the scoring
loop — the codebase's "no magic numbers" idiom and the tuning knob a future project may need.

### 3.3 Compatibility with existing tests

This **intentionally changes result order** for queries that mix confidence levels — the opposite of
v0.7.0's "no existing-test behavior change". Existing ranking-order assertions that assume pure-keyword
order are updated to the weighted order (the change is the point); new tests assert the two target
properties directly (low-confidence sinks below equal-keyword high-confidence; a strong keyword match
still surfaces despite low confidence). `n_matches`/`n_returned`/`corrupt_pages` semantics unchanged.

## 4. Change B — routing prose nudge (`hooks/handlers.py`, optional/minimal)

`_ROUTE_CHECKPOINT` already carries "wiki를 SSOT로 query하라 … exp-analyze/exp-design엔 이미 강제". The
only addition worth its bytes: nudge *ad-hoc* experiment prompts (not entering a skill) toward
exp-analyze/exp-design, whose forced query is the reliable path. **Constraint:** the checkpoint is
test-capped at ≤ 2 KiB and measures **1930 / 2048 bytes today (~118 B headroom)**, so this is achieved
by *tightening existing wording*, not net addition — and if it will not fit, it is dropped (low marginal value; ranking + adoption carry the
release). This is prose only — no execution, consistent with §1's decision.

## 5. Change C — project adoption (companion; generic, NOT part of the release code)

The shipped v0.7.0 launch gate and enumeration are **inert until a project tags its own pages**. Any
adopting project, to actually benefit, does two code-free things in its own `.omx/`:

1. **Fill `profile/rules.md`** — replace the `exp-init` example stub with the project's real analysis
   discipline that exp-analyze/exp-design read automatically. A *pointer-style* body (short
   Always/Never + a reference to the project's fuller rules doc) is the recommended shape where a
   project already maintains discipline rules elsewhere, to keep one SSOT.
2. **Status-tag open leads** — mark genuinely-open items `status: needs-experiment`, and any pending
   correction that invalidates dependent runs `status: needs-apply-before-retrain`, so the launch gate
   and `omx wiki list --status` enumeration fire.

These steps are **project-specific and stay in the project's own store** — no project content enters
this repo (INV-1). The concrete per-project execution (which leads, which rules) is tracked in that
project's own scratch/plan, not here.

## 6. File-level impact

| File | Change | Type |
|:---|:---|:---|
| `omx-core/omx_core/wiki/query.py` | `_CONFIDENCE_WEIGHT`/`_STATUS_WEIGHT` consts + weighted sort in `query_wiki` | core logic |
| `omx-core/tests/test_wiki_query.py` | update order assertions; add sink/surface property tests | tests |
| `hooks/handlers.py` | tighten `_ROUTE_CHECKPOINT` ad-hoc nudge (only if ≤ 2 KiB holds) | routing prose |
| `omx-core/tests/test_hook_*.py` | 2 KiB cap assertion stays green | tests |
| `CHANGELOG.md`, `.claude-plugin/plugin.json` | v0.7.1 release | release |

## 7. Accepted residual risk

Pure ad-hoc planning that never enters a skill still depends on the model heeding the checkpoint prose —
the direct consequence of not building the per-prompt executor (§1). Change B and project adoption
(§5.1) reduce this exposure but do not eliminate it. This trade-off was chosen deliberately over the
every-prompt cost and drift of an executor.

## 8. Testing strategy (TDD)

Test-first for the ranking change: a red test asserting a `low`-confidence page sinks below an
equal-keyword `high`-confidence page, and a red test asserting a strong keyword match on a `low` page
still ranks above a weak match on a `high` page, before touching `query.py`. Update the existing
order-dependent assertions to the weighted order in the same commit. Full `pytest` on omx-core stays
green otherwise. Separate-lane code review (no self-approval) before merge. Verification: a round-trip
smoke — seed one `high` + one `low` page with equal keyword content, `omx wiki query` returns the
`high` first; a strong-match `low` page still returns above a weak-match `high` page.

## 9. Out of scope (YAGNI)

- Per-prompt hook executor that runs `omx wiki query` (§1 rejection).
- Bulk rewrite of the ~70 stale `sources:` back-links from the group rename — the ranking change sinks
  those low-confidence stubs anyway; fix only if a specific link misdirects.
- omha routing-card changes (v0.7.0 §7 — cards emit lane name only).
- A new unified index document — `INDEX.md` already fills that role.
- Recency weighting, embedding/vector search (hard constraint: keyword only), `query --status` filter.

## 10. Amendment (2026-07-16) — route_emit backlog pre-fetch (partial reversal of §9)

The 2026-07-15 stranded-instruction incident (an open wiki lead silently dropped from a
next-steps section despite the advisory checkpoint clause) led to `route_emit` pre-fetching
the open backlog as injected data (`hooks/handlers.py:_fetch_open_backlog`, commit 5292ab9).
That commit landed as an unversioned hotfix and is regularized in v0.7.2.

Scope relative to the §1/§9 rejection: what §9 rejected was a per-prompt executor running
`omx wiki query` (topic-dependent, needs prompt parsing, unbounded relevance work). The
pre-fetch is narrower — a fixed two-value `wiki list --status` enumeration, topic-blind,
fail-open on any error, and budget-bounded. The per-prompt cost concern stands and is now
enforced rather than assumed: each subprocess call is capped at `_BACKLOG_FETCH_TIMEOUT_S`
(1.2s) so both calls fit inside run_hook's 3s SIGALRM ceiling (route_emit is deliberately
not in `_BUDGETS`); the arithmetic is pinned by `test_hook_backlog.py`. The original commit's
"8s worst case" note was wrong at runtime (SIGALRM fired first) — v0.7.2 makes the stated
and enforced bounds identical.
