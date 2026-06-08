# OMX Wiki Lint Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 4 wiki-lint enhancements (contradiction-candidate, stronger orphan, lint→gc suggestion pipe, loop reminder) to omx-core, each re-shaped to OMX's purpose while preserving INV-1 / loud-fail / injected-now / no-auto-delete.

**Architecture:** Pure-core additions in `lint.py` (A, B) and `gc.py` (C, a pure formatter), wired into the existing `cli.py` `gc` command (C), plus an `exp-loop/SKILL.md` instruction change (D). Test-first throughout; one existing orphan test is intentionally rewritten for B.

**Tech Stack:** Python 3.12, pytest, omx_core package (editable install at `/root/oh-my-experiments/omx-core/`), `omx` CLI.

**Spec:** `docs/superpowers/specs/2026-06-08-omx-wiki-lint-enhancements-design.md`
**Branch:** `exp/wiki-lint` (already created; baseline tag `baseline-260608-wiki-lint`).
**Run all tests with:** `cd /root/oh-my-experiments/omx-core && python -m pytest -q`
**Run wiki tests only:** `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_lint.py tests/test_wiki_gc.py -q`

**Decision locked from spec open question:** C's delete-suggestion candidates are **orphan only, NOT stale**. Rationale: stale = "old", not "useless"; experiment knowledge (e.g. baseline results) stays valid when old, so suggesting it for deletion risks losing valid knowledge. stale stays a report-only lint signal.

---

## Task 1: A — contradiction-candidate lint (tag-grouped)

**Files:**
- Modify: `omx-core/omx_core/wiki/lint.py`
- Test: `omx-core/tests/test_wiki_lint.py`

- [ ] **Step 1: Write the failing tests**

Append to `omx-core/tests/test_wiki_lint.py`:

```python
def test_lint_flags_contradiction_candidate_shared_tag_high_confidence(tmp_path):
    # Two HIGH-confidence pages sharing a tag -> one contradiction-candidate (a-1).
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Alpha is a floor",
                            content="alpha bounds feasibility", tags=["alpha"],
                            category="decision", confidence="high", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Alpha is a lever",
                            content="alpha expands DR range", tags=["alpha"],
                            category="decision", confidence="high", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=10240)
    cands = [i for i in res["issues"] if i["type"] == "contradiction-candidate"]
    assert len(cands) == 1
    assert cands[0]["severity"] == "info"
    assert "alpha" in cands[0]["message"]


def test_lint_no_contradiction_candidate_when_not_all_high(tmp_path):
    # Shared tag but one page is medium -> NOT a contradiction candidate (a-1 needs all-high).
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="A1", content="x",
                            tags=["alpha"], category="decision", confidence="high", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="A2", content="y",
                            tags=["alpha"], category="decision", confidence="medium", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=10240)
    assert not any(i["type"] == "contradiction-candidate" and "shared" in i["message"]
                   for i in res["issues"])


def test_lint_flags_contradiction_candidate_tag_across_categories(tmp_path):
    # Same tag in two DIFFERENT categories -> contradiction-candidate (a-2).
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="D", content="x",
                            tags=["roll"], category="decision", confidence="medium", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="B", content="y",
                            tags=["roll"], category="debugging", confidence="medium", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=10240)
    assert any(i["type"] == "contradiction-candidate" and "categor" in i["message"]
               for i in res["issues"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_lint.py -k contradiction -v`
Expected: 3 FAIL (no `contradiction-candidate` issues produced yet).

- [ ] **Step 3: Implement the detector in `lint.py`**

In `omx-core/omx_core/wiki/lint.py`, add this helper function above `lint_wiki` (after `_parse_iso`):

```python
def _contradiction_candidates(pages: dict) -> list:
    """Structural contradiction SIGNALS (INV-1: candidates only, never a verdict).

    a-1: >=2 pages sharing a tag where EVERY sharing page is confidence 'high'
         -> they may assert conflicting high-confidence conclusions; flag for review.
    a-2: a tag spanning >1 category -> classification drift; flag for review.
    One issue per tag (a-1 takes precedence over a-2 for the same tag)."""
    by_tag: dict = {}
    for slug, page in pages.items():
        for tag in page.tags:
            by_tag.setdefault(tag, []).append(page)

    issues = []
    for tag in sorted(by_tag):
        group = by_tag[tag]
        if len(group) < 2:
            continue
        slugs = sorted(g.slug for g in group)
        # a-1: all sharing pages are high-confidence
        if all(g.confidence == "high" for g in group):
            issues.append({
                "slug": slugs[0], "severity": "info", "type": "contradiction-candidate",
                "message": (f"{len(group)} high-confidence pages share tag {tag!r}; "
                            f"review whether their conclusions conflict: {', '.join(slugs)}"),
            })
            continue
        # a-2: tag spans multiple categories
        cats = sorted({g.category for g in group})
        if len(cats) > 1:
            issues.append({
                "slug": slugs[0], "severity": "info", "type": "contradiction-candidate",
                "message": (f"tag {tag!r} appears across categories {cats}; "
                            f"review for classification drift: {', '.join(slugs)}"),
            })
    return issues
```

Then, inside `lint_wiki`, after the per-page loop and before `by_type = ...`, add:

```python
    issues.extend(_contradiction_candidates(pages))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_lint.py -k contradiction -v`
Expected: 3 PASS.

- [ ] **Step 5: Run full wiki-lint suite to confirm no regression**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_lint.py -q`
Expected: all PASS (7 old + 3 new = 10).

- [ ] **Step 6: Commit**

```bash
cd /root/oh-my-experiments
git add omx-core/omx_core/wiki/lint.py omx-core/tests/test_wiki_lint.py
git commit -m "feat(wiki): contradiction-candidate lint (tag-grouped, INV-1 candidates only)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: B — stronger orphan (inbound==0) with fresh-page exemption

**Files:**
- Modify: `omx-core/omx_core/wiki/lint.py`
- Test: `omx-core/tests/test_wiki_lint.py` (rewrite 1 existing test + add 2)

- [ ] **Step 1: Rewrite the existing orphan test + add fresh-exemption tests**

In `omx-core/tests/test_wiki_lint.py`, REPLACE the whole function
`test_lint_orphan_only_when_no_links_either_direction` (currently the A→B→C-isolated test)
with these three functions:

```python
def test_lint_orphan_is_inbound_zero(tmp_path):
    # New definition: orphan = nobody links to it (inbound==0), even if it links OUT.
    # A links to B; A itself has no inbound -> A is now an orphan. C is isolated -> orphan.
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-01-01T10:00:00", title="A",
                            content="see [[B]] for more", tags=[], category="pattern",
                            confidence="high", sources=[])
    ingest.ingest_knowledge(p, now="2026-01-01T10:00:00", title="B",
                            content="body of B", tags=[], category="pattern",
                            confidence="high", sources=[])
    ingest.ingest_knowledge(p, now="2026-01-01T10:00:00", title="C",
                            content="isolated body", tags=[], category="pattern",
                            confidence="high", sources=[])
    # now is well past stale_days/2 so no fresh-exemption applies
    res = lint.lint_wiki(p, now="2026-05-31T10:00:00", stale_days=30, max_page_size=10240)
    orphans = {i["slug"] for i in res["issues"] if i["type"] == "orphan"}
    assert "a.md" in orphans          # outbound-only, no inbound -> orphan (NEW behavior)
    assert "c.md" in orphans          # isolated -> orphan
    assert "b.md" not in orphans      # linked-to (inbound) -> not orphan


def test_lint_fresh_page_exempt_from_orphan(tmp_path):
    # A page created within stale_days/2 of now is NOT an orphan yet (still growing).
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="New",
                            content="brand new isolated page", tags=[], category="pattern",
                            confidence="high", sources=[])
    # now is 5 days later; stale_days=30 -> half=15 -> 5 < 15 -> exempt
    res = lint.lint_wiki(p, now="2026-06-05T10:00:00", stale_days=30, max_page_size=10240)
    orphans = {i["slug"] for i in res["issues"] if i["type"] == "orphan"}
    assert "new.md" not in orphans


def test_lint_old_isolated_page_is_orphan_despite_exemption(tmp_path):
    # A page older than stale_days/2 and isolated IS an orphan (exemption does not apply).
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-01-01T10:00:00", title="Old",
                            content="old isolated page", tags=[], category="pattern",
                            confidence="high", sources=[])
    res = lint.lint_wiki(p, now="2026-03-01T10:00:00", stale_days=30, max_page_size=10240)
    orphans = {i["slug"] for i in res["issues"] if i["type"] == "orphan"}
    assert "old.md" in orphans
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_lint.py -k orphan -v`
Expected: `test_lint_orphan_is_inbound_zero` FAILs (`a.md` not yet flagged under old def);
`test_lint_fresh_page_exempt_from_orphan` FAILs (fresh page IS flagged under old def, since no exemption exists).
(`test_lint_old_isolated_page_is_orphan_despite_exemption` may pass coincidentally — that's fine.)

- [ ] **Step 3: Implement the new orphan rule in `lint.py`**

In `omx-core/omx_core/wiki/lint.py`, REPLACE the orphan block inside the final per-page loop.
Current code:

```python
        if not page.links and inbound.get(slug, 0) == 0:
            issues.append({"slug": slug, "severity": "info", "type": "orphan",
                           "message": "page has no inbound or outbound links"})
```

Replace with:

```python
        if inbound.get(slug, 0) == 0 and not _is_fresh(page.created, now_dt, stale_days):
            issues.append({"slug": slug, "severity": "info", "type": "orphan",
                           "message": "no page links to this page (inbound==0)"})
```

Then add this helper above `lint_wiki` (after `_parse_iso`):

```python
def _is_fresh(created: str, now_dt, stale_days: int) -> bool:
    """True if `created` is within stale_days/2 of `now` (a new seed page, exempt
    from orphan). An unparseable/absent created is treated as NOT fresh (so old or
    malformed pages can still be flagged). now_dt is the already-parsed naive now;
    None means no time basis -> nothing is fresh."""
    if now_dt is None:
        return False
    created_dt = _parse_iso(created)
    if created_dt is None:
        return False
    return (now_dt - created_dt).days <= stale_days // 2
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_lint.py -k orphan -v`
Expected: all 3 orphan tests PASS.

- [ ] **Step 5: Run full wiki-lint suite to confirm no regression**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_lint.py -q`
Expected: all PASS (now 12: 6 untouched old + 3 contradiction + 3 orphan).

- [ ] **Step 6: Commit**

```bash
cd /root/oh-my-experiments
git add omx-core/omx_core/wiki/lint.py omx-core/tests/test_wiki_lint.py
git commit -m "feat(wiki): orphan = inbound==0 with fresh-page exemption

Stricter than the old 'no links either direction': catches dead-end pages
(outbound-only). New seed pages created within stale_days/2 are exempt
(growing, not orphaned). Intentional behavior change; old orphan test rewritten.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: C — lint→gc suggestion pipe (orphan candidates)

**Files:**
- Modify: `omx-core/omx_core/wiki/gc.py` (pure formatter)
- Modify: `omx-core/omx_core/cli.py:608` (`_cmd_wiki_gc`, wire `suggestions` into output)
- Test: `omx-core/tests/test_wiki_gc.py`

- [ ] **Step 1: Write the failing test for the pure formatter**

Append to `omx-core/tests/test_wiki_gc.py`:

```python
from omx_core.wiki import gc as _gc


def test_suggest_delete_candidates_from_orphans_only():
    # Given a lint result, suggest ONLY orphan slugs as delete candidates (not stale).
    lint_res = {
        "issues": [
            {"slug": "lonely.md", "severity": "info", "type": "orphan", "message": "x"},
            {"slug": "old.md", "severity": "info", "type": "stale", "message": "y"},
            {"slug": "bad.md", "severity": "error", "type": "broken-frontmatter", "message": "z"},
        ],
        "stats": {"total_pages": 3, "by_type": {}},
    }
    out = _gc.suggest_from_lint(lint_res)
    assert out["delete_candidates"] == ["lonely.md"]   # orphan only; stale/error excluded
    # proposal_skeleton is a ready-to-edit wiki-gc proposal body with the candidate
    assert "kind: wiki-gc" in out["proposal_skeleton"]
    assert "## DELETE" in out["proposal_skeleton"]
    assert "lonely.md" in out["proposal_skeleton"]
    assert "old.md" not in out["proposal_skeleton"]


def test_suggest_from_lint_empty_when_no_orphans():
    lint_res = {"issues": [{"slug": "x.md", "severity": "info", "type": "stale", "message": "m"}],
                "stats": {"total_pages": 1, "by_type": {}}}
    out = _gc.suggest_from_lint(lint_res)
    assert out["delete_candidates"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py -k suggest -v`
Expected: 2 FAIL (`suggest_from_lint` does not exist).

- [ ] **Step 3: Implement `suggest_from_lint` in `gc.py`**

In `omx-core/omx_core/wiki/gc.py`, add this pure function (place it after `parse_gc_proposal`,
before `is_git_tracked`):

```python
def suggest_from_lint(lint_res: dict) -> dict:
    """Turn a lint result into REVIEW-ONLY gc delete candidates (INV-1: candidates,
    not a proposal; nothing is written or deleted). ONLY 'orphan' (info) slugs are
    suggested for deletion — stale is 'old' not 'useless', and error/warning types
    (broken-ref/oversized/broken-frontmatter) are fix-in-place, not delete. Returns
    {delete_candidates: [slug...], proposal_skeleton: <editable wiki-gc proposal>}.
    The human copies/edits the skeleton; gc-apply (git-guarded) is the only executor."""
    candidates = sorted({
        i["slug"] for i in lint_res.get("issues", [])
        if i.get("type") == "orphan"
    })
    delete_lines = "\n".join(f"- slug: {s}" for s in candidates) or "# (none)"
    skeleton = (
        "---\n"
        "kind: wiki-gc\n"
        "---\n\n"
        "## DELETE\n\n"
        f"{delete_lines}\n\n"
        "## MERGE\n\n"
        "# (add `- into: <survivor>` then indented `- <source>` lines to merge instead of delete)\n"
    )
    return {"delete_candidates": candidates, "proposal_skeleton": skeleton}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py -k suggest -v`
Expected: 2 PASS.

- [ ] **Step 5: Wire `suggestions` into the CLI `gc` command**

In `omx-core/omx_core/cli.py`, in `_cmd_wiki_gc` (starts at line 608), find the final line:

```python
    print(json.dumps({"lint": lint_res, "pages": pages}))
```

Replace with:

```python
    suggestions = _wiki_gc.suggest_from_lint(lint_res)
    print(json.dumps({"lint": lint_res, "pages": pages, "suggestions": suggestions}))
```

(`_wiki_gc` is already imported at cli.py:33.)

- [ ] **Step 6: Smoke-test the CLI on a tmp wiki**

Run:

```bash
cd /tmp && rm -rf wikismoke && mkdir wikismoke && cd wikismoke
omx wiki add --root . --title "Lonely Page" --category reference --content "no links here" --confidence low
omx wiki gc --root . | python3 -c "import sys,json; d=json.load(sys.stdin); print('candidates:', d['suggestions']['delete_candidates']); print('has skeleton:', 'kind: wiki-gc' in d['suggestions']['proposal_skeleton'])"
```

Expected: `candidates: ['lonely_page.md']` (orphan, old enough — actually fresh, so may be `[]`; if `[]` because fresh-exempt, re-run with an older page via the test suite instead). `has skeleton: True`.
Note: if the freshly-added page is exempt (created==now), `delete_candidates` is `[]` — that is CORRECT (the unit tests cover the populated path deterministically). The smoke only needs `has skeleton: True`.

- [ ] **Step 7: Run full wiki suite to confirm no regression**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py tests/test_wiki_lint.py -q`
Expected: all PASS (gc: 22 old + 2 new = 24; lint: 12).

- [ ] **Step 8: Commit**

```bash
cd /root/oh-my-experiments
git add omx-core/omx_core/wiki/gc.py omx-core/omx_core/cli.py omx-core/tests/test_wiki_gc.py
git commit -m "feat(wiki): lint->gc suggestion pipe (orphan delete candidates, review-only)

gc diagnosis now emits a `suggestions` block: orphan slugs pre-formatted as a
ready-to-edit wiki-gc proposal skeleton. INV-1: candidates only, nothing written
or deleted; gc-apply (git-guarded two-phase) stays the sole executor. stale
excluded by design (old != useless).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: D — end-of-iteration lint reminder (exp-loop SKILL.md)

**Files:**
- Modify: `skills/exp-loop/SKILL.md` (§6 "Audit the wiki at iteration end")

- [ ] **Step 1: Edit the SKILL.md §6 block**

In `skills/exp-loop/SKILL.md`, find this paragraph in section
`### 6. Audit the wiki at iteration end (report-only, never auto-fix)`:

```markdown
Report any `stale` / `broken-ref` / `broken-frontmatter` issues to the user in your
summary. Do NOT auto-edit or delete any page (minimum-change / review-gated rule).
```

Replace with:

```markdown
Report any `stale` / `broken-ref` / `broken-frontmatter` / `orphan` /
`contradiction-candidate` issues to the user in your summary. Do NOT auto-edit or
delete any page (minimum-change / review-gated rule).

If `lint`'s `stats.by_type` shows several `info`+ issues (orphan / stale /
contradiction-candidate accumulating), add a one-line cleanup reminder to the
summary: "wiki cleanup review suggested — run `omx wiki gc --root <root>` to see
delete candidates (orphans) and a ready-to-edit proposal skeleton." This only
SURFACES the suggestion; the human reviews and approves any `gc-apply` (the
git-guarded executor). NEVER run gc-apply automatically.
```

- [ ] **Step 2: Verify the edit is well-formed markdown**

Run: `cd /root/oh-my-experiments && grep -n "contradiction-candidate\|omx wiki gc" skills/exp-loop/SKILL.md`
Expected: shows the new lines in §6.

- [ ] **Step 3: Commit**

```bash
cd /root/oh-my-experiments
git add skills/exp-loop/SKILL.md
git commit -m "docs(exp-loop): surface orphan/contradiction lint + gc cleanup reminder

exp-loop now reports orphan + contradiction-candidate issues and, when info+
issues accumulate, reminds the user to run \`omx wiki gc\` for delete candidates.
Surface-only; gc-apply stays human-approved (review-gated).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Separate-lane code review (no self-approval)

**Files:** none (review only)

- [ ] **Step 1: Run the full omx-core suite for a clean baseline**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest -q`
Expected: all PASS, count = prior total + 8 new (3 contradiction + 3 orphan + 2 gc-suggest)
minus 1 rewritten (net +7 test functions). Record the exact number.

- [ ] **Step 2: Lint the changed files (ruff, if configured)**

Run: `cd /root/oh-my-experiments/omx-core && ruff check omx_core/wiki/lint.py omx_core/wiki/gc.py omx_core/cli.py 2>&1 | tail -20`
Expected: no NEW violations introduced by our diff (pre-existing ones in untouched code are out of scope).

- [ ] **Step 3: Dispatch a code-reviewer in a separate lane**

Use the `feature-dev:code-reviewer` agent (or `superpowers:requesting-code-review`) on the diff
`git diff baseline-260608-wiki-lint..HEAD -- omx-core/ skills/exp-loop/SKILL.md`.
Reviewer MUST confirm: (a) INV-1 held — core emits candidates, never verdicts/auto-deletes;
(b) injected-now preserved (no wall-clock added to core); (c) loud-fail unbroken;
(d) the orphan behavior change is the only intentional regression and is covered + documented.
Address any HIGH/MEDIUM findings before release. This is the no-self-approval gate.

---

## Task 6: Release v0.1.11

**Files:**
- Modify: `.claude-plugin/plugin.json` (version bump)
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Bump the version**

In `.claude-plugin/plugin.json`, change `"version": "0.1.10"` to `"version": "0.1.11"`.

- [ ] **Step 2: Add the CHANGELOG entry**

Prepend under the top heading in `CHANGELOG.md` (above the `## [0.1.10]` entry):

```markdown
## [0.1.11] - 2026-06-08

Four wiki-lint enhancements from an OMC-vs-OMX wiki source comparison, each
re-shaped to OMX purpose (INV-1 candidates-only, loud-fail, injected-now, no
auto-delete all preserved).

### Added

- **Contradiction-candidate lint.** `wiki lint` now emits `contradiction-candidate`
  (info) signals: >=2 high-confidence pages sharing a tag, or a tag spanning
  multiple categories. Structural candidates for human review only — the core never
  judges whether content actually conflicts (INV-1).
- **lint -> gc suggestion pipe.** `wiki gc` diagnosis now includes a `suggestions`
  block: orphan slugs pre-formatted as a ready-to-edit `wiki-gc` proposal skeleton,
  so cleanup no longer means hand-transcribing slugs. Review-only; `gc-apply`
  (git-guarded two-phase) stays the sole executor. stale is excluded by design
  (old != useless for experiment knowledge).

### Changed

- **Stronger orphan definition.** `orphan` is now `inbound == 0` (nobody links to
  the page), catching dead-end pages that link out but are never linked to —
  previously a page was orphan only with no links in EITHER direction. New seed
  pages (created within `stale_days/2` of now) are exempt to avoid flagging
  still-growing knowledge.
- **exp-loop wiki reminder.** The iteration-end wiki audit now also reports
  `orphan` / `contradiction-candidate` and, when info+ issues accumulate, reminds
  the user to run `omx wiki gc` for delete candidates. Surface-only.

### Verification

- omx-core full pytest suite green; +7 net wiki test functions.
- CLI smoke: `omx wiki gc` emits a valid `suggestions.proposal_skeleton`.
- Separate-lane code review confirmed INV-1 / loud-fail / injected-now intact.

### Notes

- Source analysis recorded in `claudebase/docs/reference/omc-wiki-skill-analysis.md`.
- Design + plan: `docs/superpowers/specs|plans/2026-06-08-omx-wiki-lint-enhancements*`.
- The orphan-definition change is the only intentional behavior change (one existing
  test rewritten accordingly).
```

- [ ] **Step 3: Commit the release**

```bash
cd /root/oh-my-experiments
git add .claude-plugin/plugin.json CHANGELOG.md
git commit -m "chore(release): v0.1.11 — wiki lint enhancements (contradiction/orphan/gc-pipe/reminder)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Merge exp/wiki-lint into main**

```bash
cd /root/oh-my-experiments
git checkout main
git merge --no-ff exp/wiki-lint -m "merge: wiki lint enhancements (A/B/C/D) v0.1.11"
git log --oneline -3
```

- [ ] **Step 5: Final full-suite verification on main**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest -q`
Expected: all PASS on the merged main.

- [ ] **Step 6: STOP — push is user-gated**

Do NOT `git push`. Report to the user: merged to main, version v0.1.11, all tests green,
push + marketplace update awaiting their explicit approval (repo rule: committing is
automatic, pushing is user-gated).

---

## Self-Review (filled by plan author)

- **Spec coverage:** A→Task1, B→Task2, C→Task3, D→Task4, separate-review→Task5, v0.1.11 release→Task6. All 4 enhancements + the two process requirements (TDD, separate review) covered.
- **Open question resolved:** C candidates = orphan only (not stale); locked at top of plan + in code/CHANGELOG.
- **Type consistency:** new issue type string `contradiction-candidate` used identically in Task1 code/tests and Task4/Task6 docs; `suggest_from_lint` returns `{delete_candidates, proposal_skeleton}` used identically in Task3 test + CLI wiring; `_is_fresh(created, now_dt, stale_days)` defined once, called once.
- **Invariant checks** are explicit review criteria in Task5 (INV-1 / injected-now / loud-fail).
