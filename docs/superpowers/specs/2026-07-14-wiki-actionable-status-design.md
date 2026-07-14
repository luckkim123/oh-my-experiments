# OMX Wiki Actionable-Status Convention — Design

> **Date:** 2026-07-14
> **Branch:** `exp/wiki-status` (baseline tag `baseline-260714-wiki-status`)
> **Target version:** v0.7.0
> **Source tree:** `/root/oh-my-experiments/omx-core/`
> **Scope:** omx is the reference implementation of a convention shared across the om* wiki family
> (omd/oms/omp adopt it in their own idiom; omc is the original the om* wikis were modeled on and is
> out of scope by owner decision).
> **Motivation:** Two documented incidents (below) where the wiki RECORDED actionable knowledge
> perfectly but nothing FORCED it into the artifact that depended on it. The wiki succeeds as an
> archive and silently fails as a gate.

---

## 1. The failure class + the two incidents (the acceptance test)

Each om* wiki is a Karpathy-model markdown KB (keyword+tag query, no embeddings, YAML-ish
frontmatter). It has no notion of an *open, actionable* item as a first-class enumerable state, so an
open lead sits in prose and the dependent work proceeds unaware. Two real incidents, both omx / the
`constrained-albc` project:

1. **Backlog flattened out of a summary (2026-07-14).** A campaign's broad planning audit found
   higher-value experiment leads and recorded them in prose (`DESIGN.p7_tail.md` "Post-audit gaps").
   The campaign README's next-steps summary DROPPED them and flattened the picture to one weakness.
   Because `omx wiki query` is keyword-ranked over 140+ pages, a question-scoped query never resurfaced
   the rest of the backlog across several sessions.
2. **A measured HARD-gate correction stranded (the expensive one).** The thruster allocation matrix
   (TAM) and IMU frame were physically measured on the real robot and recorded precisely in the wiki,
   with a roster page stating a HARD invalidation gate ("apply together, not piecemeal", "post-TAM
   baseline retrain"). Yet a later sim-fix batch applied the easy neighbor fixes and launched the
   baseline while the TAM row-rewrite stayed pending; the baseline's own DESIGN.md omitted TAM from its
   delta list. A baseline + 4 experiments ran on a plant model known to be physically wrong, and no
   artifact surfaced that fact.

**Acceptance test for every change:** *would the fix have caught both?* — (a) the open item is
enumerable keyword-independently, AND (b) the launch/summary boundary refuses-or-warns while it is open.

## 2. Invariants (every change MUST hold these)

- **INV-1 — core carries ZERO domain/semantic judgment.** The status *values* are workflow vocabulary
  (the harness's own actionable units, same class as the `session-log` category), NOT project domain
  content ("heavy-tail", "TAM" — those stay in the project's own wiki). The core validates the value set
  and enumerates; it never decides what an item MEANS.
- **INV-2 — append-merge, knowledge accrues without loss.** A slug collision MERGES, never overwrites.
  A status field must have an explicit merge rule that cannot silently drop a flag.
- **Loud-fail; injected `now`; no auto-fix.** Bad status → `WikiError`; a corrupt page is
  visible-skipped, never crashes an enumeration; no wall-clock in core; lint/gc stay report-only.
- **Backwards compatible.** ~140 existing pages have no status field and MUST keep working
  byte-for-byte (absent = not actionable). `schemaVersion` stays 1 (additive optional field).

## 3. Convention semantics

### 3.1 Status vocabulary — hard vs soft is a status-VALUE distinction, not a second field

| state | class | gate behavior | omx values |
|:---|:---|:---|:---|
| (absent) | not actionable | ignored | — (all existing pages) |
| soft actionable | open lead / backlog | **WARN** at boundaries, enumerable | `needs-experiment` |
| hard actionable | pending correction that **invalidates dependent runs** | **REFUSE** at the launch boundary | `needs-apply-before-retrain` |
| terminal | acted on or deliberately dropped | excluded from the backlog | `resolved` |

`blocked-on: <free text>` — an optional annotation, never a status value. A blocked lead KEEPS its
actionable status so it stays in the enumeration (a separate `blocked` status would hide gated leads —
incident 1 re-created).

**Why a status value, not a second `gate:` field or a tag:** a second field needs its own
serialize/parse/merge/validation axis and produces meaningless combinations; a tag is unvalidated, so a
typo silently disarms a HARD gate — which *is* the failure class. The hard/soft distinction is intrinsic
to *what kind of item it is* (a lead vs a pending correction), which the status value already names. One
field, one merge rule. `types.py` gets `STATUSES` and `BLOCKING_STATUSES = {"needs-apply-before-retrain"}`;
the launch gate distinguishes refuse-vs-warn by set membership.

**Lifecycle closes:** absent → actionable → `resolved`, re-openable by a later explicit actionable add.
`resolved` MUST exist because the merge rule is "absent-in-new keeps existing" (so old sessions never
clobber a flag) — status can never return to absent, so a terminal value is the only way to un-flag.
Resolution rides the normal append-merge Update section
(`omx wiki add --title <same> --status resolved --content "applied in <commit>"` flips the flag AND
records the evidence in one INV-2 merge).

**Reserve the blocking value narrowly.** `needs-apply-before-retrain` is only for facts that invalidate
dependent runs; everything else is soft. This prevents blocking-status inflation → ack fatigue →
rubber-stamped refusals.

### 3.2 On-disk keys — `status:` / `blocked-on:` (deliberate camelCase divergence)

omx serializes `qualityScore`/`schemaVersion` in camelCase, but status uses plain `status:` /
`blocked-on:` across ALL harnesses so `grep -rl '^status: needs-' <wiki-dir>` enumerates any harness's
backlog with one command — a family-wide grep parity that is itself a fallback enumeration path (and the
light harnesses' primary one). The dataclass field is `blocked_on`.

### 3.3 Serialize / parse (omx) — conditional write

Append `status:` / `blocked-on:` lines only when set (the exact `qualityScore` precedent at
`storage.py:104-107`): existing pages stay byte-identical. Parse with `fm.get("status") or None` and
never loud-fail on an unknown value at parse time (a hand-edited page must still load); lint flags typos
(§3.6).

### 3.4 Merge rules

- **ingest (INV-2):** explicit new status wins (how a lead resolves/re-opens); `None` in the new add
  keeps the existing value (old sessions and `capture.py` session stubs route through `ingest_knowledge`
  with no status, so keep-existing automatically protects a flag). Same for `blocked_on`. Unknown status
  → `WikiError` (the `CATEGORIES`/`CONFIDENCES` validation pattern).
- **gc merge (`gc.py:merge_pages`):** most-blocking/most-open wins — rank
  `needs-apply-before-retrain(3) > needs-experiment(2) > resolved(1) > None(0)`, max across
  survivor+sources; `blocked_on` survivor-first. Without this, gc-folding a duplicate silently disarms a
  HARD gate. Same shape as the confidence-max idiom already in that function.
  **Rider (pre-existing bug):** `merge_pages` today reconstructs the survivor WITHOUT
  `quality_score`/`quality_reasons` — it silently drops them on every merge. Carried in the same
  constructor edit (a separate commit for traceability).

### 3.5 Enumeration — `omx wiki list --status <value>`

`list` (not `query`) is the deterministic no-scoring catalog, so "backlog by construction" means zero
keyword involvement. `--status` is exact match; `--status resolved` works for free. Skipped (YAGNI): a
`--actionable` convenience flag (two values = two commands), a `query --status` filter (entangles
enumeration with ranked search). One shared pure helper `enumerate_pages(paths, status=None)` in
`query.py` backs both `wiki list` and the launch gate, so the gate can never drift from what the human
sees. Output adds `status`/`blocked_on` to every `wiki list` page dict (null when absent) and `status`
to the `query` match dicts.

### 3.6 Lint surfaces the backlog

Two new report-only issues in `lint_wiki`'s per-page loop:
- `open-lead` — a known non-resolved status; severity `warning` when blocking, `info` when soft. Surfaces
  the backlog at every exp-loop iteration end (intended anti-flattening).
- `unknown-status` — a status value not in `STATUSES` (info). A typo silently exits both enumeration and
  gate — precisely the failure class — so the guard is worth its few lines.

`gc.suggest_from_lint` excludes any slug carrying an `open-lead` issue from `delete_candidates`: an open
lead is typically inbound==0 (nothing links to it yet — that's *why* it's a backlog page), so today's
orphan→delete-suggestion pipeline would offer the backlog for deletion.

## 4. Forcing gate at the dependent-artifact boundary (omx: three layers)

### 4.a Pre-launch code gate — `omx queue-launch` (REFUSE; would have stopped incident 2)

In `_cmd_queue_launch`, before writing the pending-launch artifact (`paths` is already constructed):
1. `enumerate_pages(paths)` → partition into blocking (status ∈ `BLOCKING_STATUSES`) and soft.
2. **REFUSE:** any blocking page not acknowledged → nonzero rc, write NOTHING, emit
   `{"refused": true, "open_gates": [{slug, title, blocked_on}], "hint": "... resolve, or rerun with
   --ack-gate <slug> per gate"}`.
3. **Override:** `--ack-gate <slug>` (repeatable). Per-slug, no blanket `--force`: being forced to type
   the gate slug IS the mechanism; a blanket flag reproduces the silent-skip. Acked slugs are recorded
   in the pending-launch artifact as `acknowledged_gates: [...]` — the human-approval artifact now
   carries the un-applied correction (destroying "no artifact surfaced that fact").
4. **WARN:** soft actionable pages → `open_leads: {count, slugs}` in the normal success output +
   stderr note, rc 0.
5. **Degradations (backwards compatible):** no wiki dir / empty wiki → pass silently; corrupt page →
   surface, never block; unknown status → never block (a typo must not brick launches; lint makes it
   visible). Read-only wiki access, no lock.

`loop.queue_pending_launch` gains optional `open_leads` / `acknowledged_gates` params so the payload
records them; the handler computes the partition (core stays time-pure/IO-min).

### 4.b campaign-auditor backstop (`agents/campaign-auditor.md`)

Two new judgment bullets: **dropped-lead** (major) — run `omx wiki list --status needs-experiment`; an
open lead absent from the campaign's latest summary/README is a finding (incident 1 backstop).
**gated-launch** (major) — for each `launched` ledger event, cross-check
`omx wiki list --status needs-apply-before-retrain` against the event's `acknowledged_gates`; a launch
while a blocking page was open and unacknowledged is a finding (incident 2 backstop, catchable because
4.a records acks).

### 4.c Write-time prompt layer (WARN; the incident-1 primary catch)

Incident 1 happened at README write time by the main session, outside any skill. The only injection
point that fires there is the per-turn route checkpoint:
- `hooks/handlers.py` `_ROUTE_CHECKPOINT` — one sentence next to the existing wiki-first SSOT clause:
  before writing a next-steps / 미해결 / delta-list section of a README, report, DESIGN, or plan, run the
  status enumeration and reconcile; every open lead present or explicitly deferred; an open **blocking**
  item must be named in the delta list or the launch ack. (Block stays ≤ 2 KiB — test-capped.)
- `skills/exp-loop/SKILL.md` close-out and `skills/exp-design/SKILL.md` wiki-query section get the same
  reconciliation instruction.

**Rejected:** a `campaign_status` derived field (couples `campaign.py` to the wiki; the enumeration is
already one command). An exp-analyze edit (its report is run-scoped; the backlog belongs at
design/summary boundaries).

## 5. File-level impact (Phase 1 — omx)

| File | Change | Type |
|:---|:---|:---|
| `omx-core/omx_core/wiki/types.py` | `STATUSES`, `BLOCKING_STATUSES`, `WikiPage.status`/`blocked_on` | core schema |
| `omx-core/omx_core/wiki/storage.py` | conditional serialize + parse | core logic |
| `omx-core/omx_core/wiki/ingest.py` | status kwargs + validation + merge rule | core logic |
| `omx-core/omx_core/wiki/gc.py` | merge rank-carry status/blocked_on (+ quality-field bug), suggest exemption | core logic |
| `omx-core/omx_core/wiki/lint.py` | `open-lead` / `unknown-status` issues | core logic |
| `omx-core/omx_core/wiki/query.py` | `enumerate_pages` helper + match-dict `status` | core logic |
| `omx-core/omx_core/cli.py` | `wiki add/list --status`, `_cmd_queue_launch` gate, `--ack-gate` | CLI wiring |
| `omx-core/omx_core/loop.py` | `queue_pending_launch` optional `open_leads`/`acknowledged_gates` | core logic |
| `hooks/handlers.py` | write-time reconcile clause (≤ 2 KiB) | routing prompt |
| `skills/exp-loop/SKILL.md`, `skills/exp-design/SKILL.md`, `agents/campaign-auditor.md` | reconcile + backstop | skill/agent docs |
| `tests/test_wiki_*.py`, `test_queue_launch.py`, `test_cli.py` | TDD | tests |
| `CHANGELOG.md`, `.claude-plugin/plugin.json` | v0.7.0 release | release |

## 6. Testing strategy (TDD)

Test-first for every core change; each new value/behavior gets a red test before implementation. The
existing wiki + queue-launch suites must stay green (no intentional behavior change to an existing test
this time — all additions are opt-in on a new optional field). A separate-lane code review (no
self-approval) before merge. Verification: full `pytest` on omx-core + a round-trip smoke
(`omx wiki add --status needs-experiment` → `omx wiki list --status needs-experiment` →
`--status resolved` merge → excluded) + a launch-gate smoke (a `needs-apply-before-retrain` page →
`omx queue-launch` refuses).

## 7. Out of scope (YAGNI)

- omc changes (owner decision: the om* wikis were modeled on omc; it is third-party, no publish path).
- omh routing-card changes (its cards emit only lane name+description; the checkpoint's home is each
  harness's own routing hook).
- A new backlog storage / index section / scheduler / cross-harness sync layer.
- `--actionable` flag, `query --status`, `blocked-on` clear semantics, index.md open-lead markers.

## 8. Family adaptation (Phases 2-3, summarized; each harness's own reference card is the SSOT)

- **oms** — `references/wiki/README.md` status subsection (`open-gap`/`resolved` + `blocked-on:`);
  `scripts/oms_wiki_audit.py` gains a `STATUS_VALUES` set, an unknown-status check, and an open-gap
  enumeration dimension (the audit IS oms's deterministic enumeration). Gate (WARN): scholar-verify
  refuses a clean PASS while an open-gap is neither addressed nor explicitly deferred.
- **omd** — `references/wiki/README.md` subsection (`needs-revision`/`resolved`); enumeration by the
  contract-blessed grep. Gate (WARN): docs-verify/docs-learn run the grep before build/promotion.
- **omp** — no new status value (wiki notes are deliberately schema-less, and "ready to promote" is
  derivable from the existing `status: candidate` + `evidence_count`). Change = a reconcile line in
  omp-brief/omp-handoff (their "next" section vs the `omp-audit`/`lint_wiki` enumeration) + an optional
  derived `ready_to_promote` lint finding. WARN-only (no launch verb to refuse).
