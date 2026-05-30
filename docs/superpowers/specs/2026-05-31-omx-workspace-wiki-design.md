# OMX build #8 — Workspace-Specialization Wiki (Design)

> Status: DESIGN (approved 2026-05-31, pre-plan). Build-order #8 of the OMX harness.
> Parent design: `docs/design/2026-05-30-omx-experiment-harness-design.md` §8 #8 / §9 (workspace-wiki
> open item) / §10.2 (`.omx/registry/` tree) / §1 (cross-session-memory borrow row).
> Reference (re-implemented in Python, NEVER imported — §1 principle): OMC wiki
> `marketplaces/omc/src/hooks/wiki/{types,storage,ingest,query,lint}.ts`.

---

## 0. Decisions locked in this brainstorm (do not re-litigate)

| # | Decision | Rationale |
|:--|:--|:--|
| W1 | **Full parity core** — storage + ingest(append-merge) + query(keyword) + lint(orphan/stale/broken-ref/oversized), with auto `index.md` + `log.md` + file mutex. | User chose full parity over a query-only or triad-minus-lint scope. Matches OMC's proven module set. |
| W2 | **Boundary: core = pure deterministic IO/search/audit; Claude = judgment.** The core verbs accept already-decided `{title, content, tags, category, confidence}` and only store / merge / search / audit. "Should this finding be recorded, and under which category" is the SKILL's call. | OMX constitution D2/D3/H3 (deterministic IO = core, semantic judgment = skill). A rule-based category auto-mapper would violate the repo "no generic solution without evidence" / "name vs implementation" rules. OMC itself draws the line here (`ingestKnowledge` takes decided fields). |
| W3 | **`registry/` redesigned in place** — `findings/<slug>.md` = wiki pages (with frontmatter), `registry/index.md` = auto catalog (replaces the manual `INDEX.md`), `registry/log.md` = append-only chronicle, `registry/.wiki-lock` = mutex. | The existing `registry/{INDEX.md, findings/<slug>.md}` seed is empty (no current writer) → zero migration cost. Reuse + extend the existing getters. |
| W4 | **Append flow = skill calls `omx wiki add`** (autonomous selection — not every finding, only reusable ones), with an optional `--from-report <report.md>` mode where the core extracts candidate findings via `parse_findings` (loud, no-miss) and the skill selects + tags them. | Option-1 primary (boundary-clean) + Option-2 absorbed (no-miss extraction) WITHOUT a second `suggest` verb. |
| W5 | **lint consumer = `omx wiki lint` verb + exp-loop calls it at iteration end** (report-only, review-gated, NO auto-fix). | Gives Full-parity lint a real consumer; honors the repo "review-gated, never auto-delete" discipline. |
| W6 | **exp-init seeds ONE page from interview artifacts only** (objective / metric vocab / keep_policy / output_root / launch conventions; category=convention). No new interview questions, no directory scan. | Lowest-surface seed that still starts the "specialize from day one" compounding. The user's "쓸수록 특화" intent is met by the append flow (W4), not by a heavy seed. |
| W7 | **Approach A: `omx_core/wiki/` 4-module package** (types/storage/ingest/query/lint) + `omx wiki` CLI verbs. NOT a single file, NOT split core-vs-skill. | Matches the build #0–#6 `omx_core/<module>.py` + CLI verb + unit-test pattern; follows OMC's verified responsibility boundaries; keeps each file focused (brainstorming "focused files" principle). |
| W8 | **corrupt-page policy = skip + report** — `query`/`list` skip a page with broken frontmatter but surface it in a `corrupt_pages: [...]` field; `lint` flags it as a `broken` issue. NOT silent-skip (OMC's default), NOT whole-command loud-fail. | A visible-skip middle ground: one corrupt page never blocks the whole knowledge search (availability), yet it is never silent (repo "no silent fallback" rule). lint drives the fix. |

### 0.1 The two governing invariants (the heart of build #8 — enforced at review)

These are the user's two re-stated requirements, promoted to invariants the implementation and the
FINAL review MUST verify:

- **INV-1 — Generality (범용성, deployable to any workspace).** The wiki core
  (`omx_core/wiki/`) contains **zero** domain knowledge: no isaaclab/uuv/metric names, no absolute
  paths, no private repo names. The 8 categories are domain-neutral; `tags`/`title`/`content` are all
  runtime inputs. The core is an **empty general engine** — identical for every researcher who installs
  OMX. Shipped (public-repo) content uses placeholders only.
- **INV-2 — Per-workspace compounding (쓸수록 특화).** Specialization lives in the **data**
  (the pages under `.omx/registry/`), never in the core. exp-init seeds the workspace's conventions →
  every analyze/design appends that workspace's own findings → the next run queries the accumulation.
  **append-only merge** guarantees knowledge accrues without loss (a revisited topic gets a new
  timestamped section, deepening — never overwriting). CJK-bigram tokenization makes a Korean-research
  workspace searchable in Korean. The measurable signal: `omx wiki list` page-count + `sources` length
  grow ⇒ OMX is more specialized to that workspace; lint's stale-detection keeps the specialization fresh.

INV-1 and INV-2 are the two-layer architecture the user named: *범용 엔진 + 워크스페이스별 누적 지식*.

---

## 1. Architecture — `omx_core/wiki/` (4 modules, one responsibility each)

```
omx_core/wiki/
├── __init__.py        # public surface: WikiPage, ingest_knowledge, query_wiki, lint_wiki, WikiError
├── types.py           # WikiPage dataclass + frontmatter schema + 8 categories + confidence + WIKI_SCHEMA_VERSION
├── storage.py         # pure IO: parse/serialize frontmatter, safe slug path (traversal-blocked),
│                       #   read_page/write_page/list_pages, update_index (auto catalog),
│                       #   append_log, with_wiki_lock (file mutex via fcntl on .wiki-lock)
├── ingest.py          # ingest_knowledge: new page OR slug-collision append-merge
│                       #   (tag union / source append / confidence max / content as timestamped
│                       #    section — NEVER replace), [[link]] extraction
├── query.py           # tokenize (Latin+digits + CJK bigram → Korean) + tag>title>content scoring
│                       #   + snippet + corrupt-page skip-and-report
└── lint.py            # lint_wiki: orphan / stale / broken-ref / oversized / broken-frontmatter audit (report-only)
```

**Responsibility boundaries (each module holds in context alone):**
- `types` = schema only (data, no logic). `storage` = "disk + frontmatter" (no search/merge logic).
- `query` = read-only search (no writes). `ingest` = write/merge (no search). `lint` = audit/report (no mutation).
- Every path comes from an `omx_paths` getter (path-SSOT). Every write goes through the existing
  `atomic_path` **inside** the new file-lock.
- **100% Claude-free** — all 4 modules unit-testable with zero Claude/network/Isaac dependency; they join
  the existing suite (currently 316 passed / 1 skipped).

**Time injection (build #6 lesson, reused):** OMC calls `new Date()` inside storage; OMX instead has the
**CLI layer inject an ISO `now` string** into the core functions (`created`/`updated`/log timestamp /
lint stale-cutoff are parameters, never read from a wall clock inside the core). This keeps the core
deterministic and testable without a clock — exactly as `compute_deadline` did in build #6.

---

## 2. Data flow — the 4-skill integration points (how "쓸수록 특화" actually runs)

```
exp-init  ──seed──▶  wiki: 1 page from interview artifacts (W6)
                         category=convention, title="<profile> experiment conventions"
                         content: objective / metric vocab / keep_policy / output_root / launch conventions
                         ▼
exp-analyze ─query─▶  before analysis: omx wiki query "<run topic / metric>"
                         → past accumulated knowledge as analysis context
            ─add───▶  after analysis: select reusable findings → omx wiki add
                         (--from-report: core extracts candidates via parse_findings; Claude selects + tags + categorizes)
                         ▼
exp-design ─query─▶  before the 3-lane diagnosis: omx wiki query "<diagnosis topic>"
                         → past diagnoses / probes for the same symptom (avoid re-diagnosing)
            ─add───▶  (optional) record a confirmed diagnosis as category=decision/pattern
                         ▼
exp-loop   ─query+add per iteration (delegated analyze/design each do their own)
            ─lint──▶  at iteration end: omx wiki lint → report stale/orphan/broken (review-gated, no auto-fix)
```

**Design principles of the flow:**
1. **query = read-only grounding** at the *start* of analyze/design — pulls prior knowledge into context
   (isomorphic to exp-init's existing "Grounding in existing data" pattern). Accumulated knowledge makes
   the next run smarter (INV-2).
2. **add = autonomous selection** — dumping every finding is noise; the skill (Claude) judges "reusable
   only". `--from-report` makes the core extract candidates with no miss (W4); selection + meaning are Claude's.
3. **What triggers query/add = explicit SKILL.md steps**; the core provides verbs only, the skill owns the
   call site. To prevent the skill forgetting, each SKILL.md adds "query before / add after" as an
   **explicit hard constraint** (same pattern exp-analyze already uses for session-id / promote-plots).
4. **append-only safety** — a revisited slug never overwrites; it appends a timestamped section (OMC ingest
   strategy). Knowledge accrues, never lost — consistent with the repo `model-trim-disaster` / loud-fail ethos.

**Boundary with `report.md` (keep distinct):** wiki pages live ONLY in `.omx/registry/` (permanent,
grep-able). exp-analyze's `report.md` (in the permanent OUTPUT tree) is **separate** — `report.md` is "the
full deliverable of *this* analysis"; wiki is "compressed knowledge reused *across* analyses". Different
lifetimes, different purposes (§10.1 vs §10.2 split preserved).

---

## 3. Components

### 3.1 CLI verbs — `omx wiki <sub>` (build #6 `omx loop-status` pattern; OmxError → SystemExit)

```bash
omx wiki add --root <r> --title T --category C --tags "a,b" --confidence high|medium|low --content - (stdin)
   # add (write mode): core calls ingest_knowledge with the explicit {title, content, tags, category,
   #   confidence}. ALWAYS the path that actually writes a page. CLI injects ISO now.
   #   rc 0 + {action: created|updated, slug, index_updated: true} / rc 2 loud-fail.

omx wiki add --root <r> --from-report <report.md>
   # add (extract-only mode): core prints candidate findings as JSON (via parse_findings) and EXITS
   #   WITHOUT writing anything. The skill reads the candidates, selects the reusable ones, decides
   #   category/tags, then calls `omx wiki add` in write mode (above) once per chosen page.
   #   --from-report is mutually exclusive with the write-mode flags (a single verb, two disjoint modes).
   #   rc 0 + {candidates:[{claim, evidence, confidence}, ...]} / rc 2 loud-fail (malformed report).

omx wiki query --root <r> <query text> [--tags a,b] [--category C] [--limit N]
   # core query_wiki. rc 0 + {n_matches, matches:[{slug,title,score,snippet,category,confidence}],
   #   corrupt_pages:[slug,...]}. Empty result = n_matches:0 (NOT loud-fail). Scoring = core; reading = skill.

omx wiki lint --root <r> [--stale-days 30] [--max-page-size 10240]
   # core lint_wiki. rc 0 + {issues:[{slug,severity,type,message}], stats:{...}}. Audit only — zero auto-fix.
   #   CLI injects ISO now (for stale).

omx wiki list --root <r>
   # index.md-based catalog (slug · title · category, one per line). Fast lookup. Reports corrupt_pages too.
```

### 3.2 frontmatter schema (OMC-borrowed, OMX vocabulary)

```yaml
---
title: "<human-readable>"
tags: ["heavy-tail", "roll", "dr-hard"]      # search keys
created: 2026-05-31T...                        # CLI-injected ISO
updated: 2026-05-31T...
sources: ["20260531-143022-compare"]           # contributing analysis_id / session_id (traceability)
links: ["other-slug"]                          # [[link]] cross-references (auto-extracted)
category: pattern                              # 8: architecture/decision/pattern/debugging/
                                               #    environment/session-log/reference/convention
confidence: high                              # high/medium/low
schemaVersion: 1
---
# <title>
<markdown content>
```

### 3.3 `omx_paths` extension (registry/ redesign — W3)

```python
# existing: registry_index() → registry/INDEX.md,  finding(slug) → registry/findings/<slug>.md
# new / changed:
def wiki_page(self, slug) -> Path:   # registry/findings/<slug>.md  (succeeds finding(); keeps _check_token traversal block)
def wiki_index(self) -> Path:        # registry/index.md  (auto catalog; replaces manual INDEX.md)
def wiki_log(self) -> Path:          # registry/log.md  (append-only)
def wiki_lock(self) -> Path:         # registry/.wiki-lock  (file mutex)
def wiki_dir(self) -> Path:          # registry/findings/  (list_pages target)
```

- `finding(slug)` is **renamed** to `wiki_page(slug)` (no alias kept, to avoid two names for one path).
  The manual `registry_index()` → `INDEX.md` is **replaced** by the auto-regenerated `wiki_index()` →
  `index.md` (old getter removed). **Verified callers (2026-05-31): zero in production code; 5 references
  in `test_omx_paths.py`** (lines 210/211/218/260/502/503). Those tests are updated to the new getter names
  in the same task (T1) — so the rename is contained and breaks nothing outside the test that owns it.

### 3.4 file-lock implementation

OMC uses a bespoke `withFileLockSync`. OMX uses stdlib `fcntl.flock` (Linux/Docker is the confirmed env)
on `registry/.wiki-lock`, with timeout + retry. Combined with the existing `atomic_path`: inside the lock,
write the page + regenerate the index (OMC's `writePage` = lock + updateIndex pattern, re-implemented).

---

## 4. Error handling (loud-fail discipline — repo constitution + build #0–#6 consistency)

- **slug traversal** → `_check_token` blocks `..`/separators (existing); safe-path violation → `WikiError`.
- **corrupt frontmatter (W8)** → `query`/`list` skip the page but surface it in `corrupt_pages:[...]`
  (visible-skip, NOT silent — repo "no silent fallback"); `lint` flags it as a `broken` issue. One corrupt
  page never blocks the whole search. (Isomorphic to build #6 `read_pending_launch` corrupt-JSON handling,
  adapted for availability.)
- **reserved files** → writing a page named `index.md`/`log.md` raises (OMC RESERVED_FILES pattern).
- **lock timeout** → after the timeout, `WikiError` (another session holds it — concurrency made visible;
  repo `concurrent-session` rule).
- **empty query result** → NOT loud-fail (normal). Query on an empty wiki = `n_matches:0`.

---

## 5. Testing + build order

### 5.1 Tests (build #0–#6 pattern, join the 316-test suite; time-injected → deterministic)

- `test_wiki_types.py` — frontmatter serialize/deserialize round-trip, 8-category validation, schemaVersion.
- `test_wiki_storage.py` — parse/serialize, slug traversal block (`../escape`), reserved-file refusal,
  auto index regeneration, log append, corrupt frontmatter → corrupt_pages reporting.
- `test_wiki_ingest.py` — new page creation, slug-collision **append-merge** (tag union / source append /
  confidence max / content never destroyed), `[[link]]` extraction.
- `test_wiki_query.py` — tokenize (Latin+digits + **CJK bigram Korean**), tag>title>content ordering,
  snippet, empty=0 (not loud-fail), sort.
- `test_wiki_lint.py` — orphan / stale (time-injected) / broken-ref / oversized / broken-frontmatter + stats.
- `test_cli.py` (extend) — `omx wiki add/query/lint/list` rc 0/2, `--from-report` extraction,
  OmxError→SystemExit, now injection.
- `test_omx_paths.py` (extend) — `wiki_page/wiki_index/wiki_log/wiki_lock/wiki_dir` + slug validation.
- `test_core_import_safe.py` (extend) — wiki exports.

### 5.2 Build order (TDD task units; writing-plans details them)

```
T1  omx_paths: wiki_page/wiki_index/wiki_log/wiki_lock/wiki_dir getters (finding → wiki_page succession)
T2  wiki/types.py — WikiPage dataclass + schema + category/confidence
T3  wiki/storage.py — frontmatter parse/serialize + safe path + read/write/list
T4  wiki/storage.py — update_index (auto catalog) + append_log + file-lock (fcntl)
T5  wiki/ingest.py — ingest_knowledge append-merge + [[link]] extraction
T6  wiki/query.py — tokenize (CJK) + scoring + snippet + corrupt-skip reporting
T7  wiki/lint.py — orphan/stale/broken-ref/oversized/broken-frontmatter audit
T8  wiki/__init__.py + omx_core export
T9  cli.py — omx wiki add/query/lint/list verbs (now injection, --from-report)
T10 skills integration — exp-init seed / exp-analyze query+add / exp-design query / exp-loop lint
    (add explicit SKILL.md steps; edit the 4 skill bodies)
T11 docs/HANDOFF/MEMORY update + plugin.json check (wiki = core + skill-integration; NO new skill dir)
FINAL  opus cross-cutting review (boundary / INV-1 generality / INV-2 compounding / loud-fail /
       path-SSOT / append-only / repo discipline)
```

**plugin.json impact:** wiki is NOT a new skill — it integrates into the existing 4 skills + adds core verbs.
The `skills` array stays at 4 (exp-init/analyze/design/loop). No new skill directory.

**Execution:** same as build #0–#6 — `superpowers:writing-plans` → `subagent-driven-development`
(fresh implementer per task + spec & quality review → opus FINAL → finishing-a-development-branch =
local main; push only on explicit user authorization).

---

## 6. Scope guards (what build #8 does NOT do)

- **No vector embeddings** — keyword + tag + grep only (OMC hard constraint; OMX D1/D2 minimal surface).
- **No auto-fix in lint** — report only; the human/cleanup decides (review-gated).
- **No directory scan in the seed** (W6) — interview artifacts only.
- **No new interview questions** in exp-init — the seed rides on what the interview already elicits.
- **No `report.md` replacement** — the wiki is a separate compressed-knowledge layer, not a deliverable.
- **No auto-launch / no training** — unchanged from the whole OMX harness (D4/B8).
```
