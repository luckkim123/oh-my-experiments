# Wiki Retrieval Ranking (v0.7.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `omx wiki query` rank confidence/status-aware so low-confidence auto-captured stubs stop burying curated pages, while keyword relevance stays the dominant ranking term (metadata breaks near-tied scores).

**Architecture:** One localized change to `omx_core/wiki/query.py`: multiply the existing integer keyword score by two lookup-table weights (`confidence`, `status`) at sort time. Keyword score is the dominant term — individual weights are in `[0.70, 1.00]` (worst-case combined `low`×`resolved` = 0.56), so a clearly-stronger keyword match wins, while metadata intentionally breaks near-tied scores (within ~1.8×) — the stub-sinking. Not strict keyword primacy (incompatible with meaningful weighting). Read-only, no page mutated or filtered (INV-2). Then a v0.7.1 patch release.

**Tech Stack:** Python 3.10+, pytest. omx-core package; plugin versioned via `.claude-plugin/plugin.json`.

## Global Constraints

- **Keyword-only search** — no embeddings/vector search (hard constraint in `query.py` docstring). This change adds NO new query signal, only re-weights the existing keyword score.
- **INV-1** — core carries zero domain judgment; `confidence`/`status` are workflow fields, weighting by them is allowed. No project vocabulary enters core.
- **INV-2** — ranking is read-only; no page is dropped, hidden, or filtered — only re-ordered.
- **Backwards compatible** — a page with absent `confidence`/`status` gets a neutral weight and keeps surfacing. No new required field; `schemaVersion` unchanged.
- **Version SSOT** — `.claude-plugin/plugin.json` `version` is the SSOT; `omx-core/pyproject.toml` MUST match; sync via `python3 scripts/sync_version.py` (never hand-edit pyproject). Enforced by `tests/test_version_sync.py`.
- **Checkpoint cap** — `_ROUTE_CHECKPOINT` must stay `<= 2048` bytes UTF-8 (asserted `tests/test_hook_handlers_r3.py:65`; currently 1930).
- **No AI-attribution strings** in any file or commit message (repo/project rule).
- **Isolation** — all code changes on branch `exp/wiki-ranking` off `main`, with annotated baseline tag `baseline-260714-wiki-ranking` (repo comparison-experiment isolation convention). Merge to `main` only after a separate-lane code review passes.
- **Commit style** — Conventional Commits as in the repo log (`feat(wiki):`, `test(wiki):`, `docs:`, `release(omx):`).

---

### Task 1: Confidence/status-aware ranking in `query_wiki`

**Files:**
- Modify: `omx-core/omx_core/wiki/query.py` (add two module constants after the regex constants ~line 17; change the sort at line 129)
- Test: `omx-core/tests/test_wiki_query.py` (add three tests; existing tests unchanged)

**Interfaces:**
- Consumes: `query.query_wiki(paths, *, now, text, tags=None, category=None, limit=20)` and `ingest.ingest_knowledge(..., confidence=..., status=...)` — both already exist.
- Produces: no signature change. `query_wiki` still returns `{n_matches, n_returned, matches, corrupt_pages}`; `matches` order now reflects `keyword_score * confidence_weight * status_weight`. Module constants `_CONFIDENCE_WEIGHT: dict[str|None, float]` and `_STATUS_WEIGHT: dict[str|None, float]`.

**Note for the implementer:** the existing `test_wiki_query.py` tests all use `confidence="high"` and no `status`, so every page there gets weight `1.0 * 1.0` — the weighted order equals the old keyword order and they MUST stay green unchanged. Do not edit them; only verify they still pass.

- [ ] **Step 0: Branch + baseline tag**

```bash
cd /root/oh-my-experiments
git checkout main && git pull --ff-only 2>/dev/null; git checkout -b exp/wiki-ranking
git tag -a baseline-260714-wiki-ranking -m "baseline before confidence/status ranking (v0.7.1); compares against v0.7.0 keyword-only ranking"
```

- [ ] **Step 1: Write the failing tests**

Add to `omx-core/tests/test_wiki_query.py`:

```python
def test_query_low_confidence_sinks_below_equal_keyword_high(tmp_path):
    # same keyword content, different confidence -> high ranks first (was a tie).
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Heavy tail",
                            content="body", tags=[], category="pattern",
                            confidence="low", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Heavy tail",
                            content="body", tags=[], category="pattern",
                            confidence="high", sources=[])
    res = query.query_wiki(p, now="2026-05-31T10:01:00", text="heavy tail")
    assert res["n_matches"] == 2
    assert res["matches"][0]["confidence"] == "high"   # high wins the tie
    assert res["matches"][1]["confidence"] == "low"


def test_query_strong_keyword_low_still_outranks_weak_high(tmp_path):
    # low-confidence TITLE match (score 5 -> 4.0) beats high-confidence CONTENT
    # match (score 2 -> 2.0): keyword relevance stays primary.
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Heavy tail",
                            content="unrelated", tags=[], category="pattern",
                            confidence="low", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Other",
                            content="this mentions heavy tail once", tags=[],
                            category="pattern", confidence="high", sources=[])
    res = query.query_wiki(p, now="2026-05-31T10:01:00", text="heavy tail")
    assert res["matches"][0]["title"] == "Heavy tail"   # low+title beats high+content


def test_query_resolved_status_demoted_on_tie(tmp_path):
    # equal keyword + equal confidence; a resolved page sinks below a non-actionable one.
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Heavy tail",
                            content="body", tags=[], category="pattern",
                            confidence="high", sources=[], status="resolved")
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Heavy tail",
                            content="body", tags=[], category="pattern",
                            confidence="high", sources=[])
    res = query.query_wiki(p, now="2026-05-31T10:01:00", text="heavy tail")
    assert res["matches"][0]["status"] is None       # active page first
    assert res["matches"][1]["status"] == "resolved"  # resolved demoted
```

- [ ] **Step 2: Run the new tests, verify they FAIL**

Run: `cd /root/oh-my-experiments/omx-core && python3 -m pytest tests/test_wiki_query.py::test_query_low_confidence_sinks_below_equal_keyword_high tests/test_wiki_query.py::test_query_strong_keyword_low_still_outranks_weak_high tests/test_wiki_query.py::test_query_resolved_status_demoted_on_tie -v`

Expected: the two tie tests FAIL (current keyword-only sort makes the order arbitrary/insertion, so the high/active page is not guaranteed first). The strong-keyword test may already pass (title 5 > content 2 even without weights) — that is fine, it guards the primary-keyword invariant against the upcoming change.

- [ ] **Step 3: Implement the weights + weighted sort**

In `omx-core/omx_core/wiki/query.py`, add after the `_CJK` regex constant (~line 17):

```python
# Ranking weights (v0.7.1): keyword score stays primary — every weight is in
# [0.70, 1.00], so a strong keyword match dominates regardless of metadata.
# These are the tuning knob; adjust here, not inline. absent (None) = neutral.
_CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.92, "low": 0.80, None: 0.90}
_STATUS_WEIGHT = {
    "needs-experiment": 1.0,
    "needs-apply-before-retrain": 1.0,
    "resolved": 0.70,
    None: 1.0,
}


def _rank_weight(match: dict) -> float:
    """Weighted rank key: keyword score modified by confidence + status.
    Unknown/absent metadata -> neutral (never penalize a hand-edited value)."""
    conf = _CONFIDENCE_WEIGHT.get(match["confidence"], 0.90)
    stat = _STATUS_WEIGHT.get(match["status"], 1.0)
    return match["score"] * conf * stat
```

Then replace the sort at line 129:

```python
    matches.sort(key=lambda m: (_rank_weight(m), m["score"]), reverse=True)
```

(The `m["score"]` secondary key keeps a deterministic order when two pages weight equally.)

- [ ] **Step 4: Run the new tests + the whole query suite, verify PASS**

Run: `cd /root/oh-my-experiments/omx-core && python3 -m pytest tests/test_wiki_query.py -v`
Expected: all tests PASS — the three new ones and all eight pre-existing ones (the pre-existing ones use uniform `high` confidence, so their order is unchanged).

- [ ] **Step 5: Commit**

```bash
cd /root/oh-my-experiments
git add omx-core/omx_core/wiki/query.py omx-core/tests/test_wiki_query.py
git commit -m "feat(wiki): confidence/status-aware query ranking (keyword stays primary)"
```

---

### Task 2: v0.7.1 release (version bump + CHANGELOG)

**Files:**
- Modify: `.claude-plugin/plugin.json` (version SSOT)
- Generated: `omx-core/pyproject.toml` (via sync script — do not hand-edit)
- Modify: `CHANGELOG.md` (new `[0.7.1]` entry at top)

**Interfaces:** none (release metadata only).

- [ ] **Step 1: Bump the version SSOT**

Edit `.claude-plugin/plugin.json` line 3: `"version": "0.7.0"` -> `"version": "0.7.1"`.

- [ ] **Step 2: Sync the derived version**

Run: `cd /root/oh-my-experiments && python3 scripts/sync_version.py`
Expected: exit 0; `omx-core/pyproject.toml` version now `0.7.1`.

- [ ] **Step 3: Verify version sync test passes**

Run: `cd /root/oh-my-experiments/omx-core && python3 -m pytest tests/test_version_sync.py -v`
Expected: PASS (plugin.json == pyproject).

- [ ] **Step 4: Add the CHANGELOG entry**

Insert directly above the `## [0.7.0]` line in `CHANGELOG.md`:

```markdown
## [0.7.1] - 2026-07-14 — confidence/status-aware wiki query ranking

### Changed

- **`omx wiki query` now ranks confidence/status-aware.** The keyword score is
  multiplied by a confidence weight (`high` 1.0, `medium` 0.92, `low` 0.80, absent
  0.90) and a status weight (`resolved` 0.70, else 1.0) before sorting. Keyword
  relevance is the dominant term — individual weights are in `[0.70, 1.00]` (combined
  worst case 0.56); a clearly-stronger keyword match wins, while metadata intentionally
  breaks near-tied scores (the stub-sinking).
  Motivation: ~65 low-confidence auto-captured `session-log` stubs previously tied
  with curated pages and buried them. No page is filtered or hidden — only re-ordered
  (INV-2); pages with absent metadata keep surfacing (neutral weight). Design + plan:
  `docs/superpowers/specs/2026-07-14-wiki-retrieval-ranking-design.md`.

### Deferred

- A route-checkpoint prose nudge for ad-hoc experiment prompts was evaluated and
  dropped: `_ROUTE_CHECKPOINT` has ~118 B of headroom under its 2 KiB cap and already
  routes ad-hoc work to the query-forcing exp-analyze/exp-design skills, so the
  byte-squeeze was not worth its marginal value.
```

- [ ] **Step 5: Full suite green**

Run: `cd /root/oh-my-experiments/omx-core && python3 -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /root/oh-my-experiments
git add .claude-plugin/plugin.json omx-core/pyproject.toml CHANGELOG.md
git commit -m "release(omx): v0.7.1 — confidence/status-aware wiki query ranking"
```

---

### Change B — deferred (not a task)

The spec's optional route-checkpoint nudge is **dropped**, recorded in the CHANGELOG `### Deferred` note above. Rationale carried from the spec (§4) and confirmed by measurement: 1930/2048 bytes leaves ~118 B, and the existing checkpoint already names the forcing skills. No file change. If a future need appears, it returns as its own patch.

---

### Review + merge (handled by the execution sub-skill)

subagent-driven-development runs a spec-compliance + code-quality review per task (the required separate-lane, no-self-approval gate). After Task 2's review passes, finish the branch with superpowers:finishing-a-development-branch (merge `exp/wiki-ranking` -> `main`, keep the `baseline-260714-wiki-ranking` tag in history). Do NOT `git push` unless the user asks (project rule: push is user-gated).

---

## Self-Review

**1. Spec coverage:**
- Change A (ranking) → Task 1. ✓
- Change B (routing nudge) → deferred with rationale (spec §4 explicitly permits dropping). ✓
- Project adoption (§5) → out of scope for this code plan by design (code-free project ops). ✓
- Testing strategy (§8: red tests for sink + primary-keyword; existing suite green) → Task 1 Steps 1-4. ✓
- Release (§6: CHANGELOG + plugin.json) → Task 2. ✓
- Separate-lane review (no self-approval) → execution sub-skill + finishing-a-development-branch. ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows real code; weights are concrete values, not "appropriate weights". ✓

**3. Type consistency:** `_CONFIDENCE_WEIGHT`/`_STATUS_WEIGHT`/`_rank_weight` used consistently; `_rank_weight` consumes the `match` dict keys (`score`, `confidence`, `status`) that `query_wiki` already builds at query.py:123-127. Sort key returns `(float, int)` tuple — valid for `list.sort`. ✓
