# OMX Wiki Lint Enhancements — Design

> **Date:** 2026-06-08
> **Branch:** `exp/wiki-lint` (baseline tag `baseline-260608-wiki-lint`)
> **Target version:** v0.1.11
> **Source tree:** `/root/oh-my-experiments/omx-core/`
> **Motivation:** A source-level comparison of OMC's wiki skill vs the OMX wiki found four gaps. This
> design closes them, each re-shaped to OMX's purpose rather than copied verbatim.

---

## 1. Invariants (every change MUST hold these)

These are OMX wiki's existing contracts; the enhancements are designed to never break them:

- **INV-1 — core carries ZERO domain/semantic judgment.** The core emits *structural candidates and
  signals*; deciding what a candidate MEANS (is it really a contradiction? should it be deleted?) is the
  SKILL's (Claude's) job, and acting on it is the human's. No change here may make the core *judge content*.
- **Loud-fail.** Bad inputs raise `WikiError`; a corrupt page is visible-skipped + reported, never
  silently swallowed and never crashes the whole audit.
- **Injected `now`.** No wall-clock inside core. All time-dependent logic takes the caller's naive-ISO
  `now`, keeping lint/gc deterministic and unit-testable.
- **No auto-fix / no auto-delete.** lint and gc-diagnosis are report-only. Destruction goes only through
  the existing two-phase git-guarded `gc-apply` on a human-approved proposal.

## 2. The four enhancements

### A. Contradiction-candidate detection (lint)

**Problem.** OMC flags `structural-contradiction` by slug-prefix groups with conflicting confidence.
OMX experiment slugs carry dates, so prefixes don't group; the real risk in an experiment KB is two
high-confidence pages on the *same topic* asserting opposite conclusions (e.g. "alpha is a feasibility
floor" vs "alpha is an expansion lever").

**Design.** New lint issue type `contradiction-candidate` (severity `info`). Two structural signals,
NO semantic judgment (INV-1):
- **a-1:** Pages grouped by *shared tag*; if ≥2 pages share a tag AND all carry `confidence: high`,
  emit one candidate per such tag-group. Message is a *review request*: "N high-confidence pages share
  tag 'X' — review whether their conclusions conflict: <slugs>". (Tag-based grouping fits OMX notes;
  slug-prefix grouping from OMC does not.)
- **a-2:** A tag that appears across pages of *different categories* (OMC parity) — e.g. same tag in
  `decision` and `debugging` signals classification drift. One candidate per such tag.

Emitted once per tag-group (dedupe), `info` severity, never auto-actioned.

### B. Orphan definition strengthened (lint)

**Change.** Current OMX orphan = `not page.links and inbound == 0` (no links *either* direction).
New = `inbound == 0` (nobody links to it — OMC's stricter definition), so dead-end pages (I link out
but nobody reads me) are caught.

**OMX-specific guard against noise:** A freshly-created seed page legitimately has no inbound links
yet. So **exempt pages whose `created` is within `stale_days / 2` of `now`** ("new pages are growing,
not orphaned"). This is an OMX addition not in OMC, computable deterministically because `now` is
injected. Pages with an unparseable `created` are treated as NOT-recent (so they can still be flagged).

**Test impact:** existing `test_lint_orphan_only_when_no_links_either_direction` encodes the OLD
definition and MUST be rewritten — under the new rule `a.md` (outbound-only, old enough) becomes an
orphan. This is an intentional behavior change, documented in CHANGELOG.

### C. lint→gc candidate pipe (gc diagnosis)

**Correction to the original analysis.** `omx wiki gc` already exists as a read-only diagnosis
(`lint` result + page metadata as JSON). C is not new infra — it *completes* that diagnosis.

**Design.** Add a `suggestions` field to the `gc` diagnosis output: pre-format the `info`-severity
orphan/stale slugs lint found into the gc-proposal `## DELETE` candidate shape, so a human/skill can
copy them into a proposal instead of hand-transcribing. **INV-1 sacrosanct:** these are *candidates for
review*, not a proposal — no file is written, nothing is deleted, `gc-apply`'s git-guarded two-phase
stays the only execution path. Only `info` orphan/stale qualify (never `error`/`warning` types like
broken-ref/oversized — those are fix-in-place, not delete). The formatting helper lives in `gc.py`
(pure, testable); the CLI wires it into the existing `gc` command output.

### D. End-of-iteration lint reminder (skill, not core)

**No OMC-style auto-capture** (wrong fit for a CLI architecture, and low-value even in OMC). Instead,
strengthen `exp-loop/SKILL.md`'s existing "audit the wiki at iteration end" step: when `lint`'s
`stats.by_type` shows `info`+ issues at/above a small threshold, the skill prints a one-line
"cleanup review suggested (run `omx wiki gc` to see candidates)". This is a SKILL.md instruction change
+ relies on data already in the lint output — **no core code change**, honoring INV-1 (the skill judges
the threshold, the core just reports counts).

## 3. File-level impact

| File | Change | Type |
|:---|:---|:---|
| `omx-core/omx_core/wiki/lint.py` | A (contradiction-candidate), B (orphan + fresh-exempt) | core logic |
| `omx-core/omx_core/wiki/gc.py` | C (suggestion formatter, pure helper) | core logic |
| `omx-core/omx_core/cli.py` | C (wire `suggestions` into `gc` output) | CLI wiring |
| `skills/exp-loop/SKILL.md` | D (reminder instruction) | skill doc |
| `omx-core/tests/test_wiki_lint.py` | A/B tests; rewrite orphan test | tests |
| `omx-core/tests/test_wiki_gc.py` | C suggestion-formatter tests | tests |
| `CHANGELOG.md`, `.claude-plugin/plugin.json` | v0.1.11 release | release |

## 4. Testing strategy (TDD)

Test-first for every core change (A, B, C). Each new issue type / behavior gets a red test before
implementation. Existing 63 wiki tests must stay green except the one intentional orphan-test rewrite.
After implementation, a separate-lane code-review pass (no self-approval) before merge. Verification:
full `pytest` on omx-core + `omx wiki lint`/`omx wiki gc` smoke on a tmp wiki.

## 5. Out of scope (YAGNI)

- Semantic contradiction detection (needs an LLM; that is the SKILL's job by INV-1, not core's).
- Session lifecycle hooks (OMX is CLI; D covers the loop-integration need instead).
- Any change to query scoring, the CJK tokenizer, ingest merge, or gc-apply's execution path.
