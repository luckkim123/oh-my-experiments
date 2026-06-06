# omx wiki gc Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an omx wiki maintenance feature — a read-only `wiki gc` diagnosis verb and a two-phase, git-guarded `wiki gc-apply` execution verb — so semantically-overlapping or superseded wiki pages can be merged/deleted under a human gate without ever losing recovery.

**Architecture:** The core carries zero semantic judgment. `gc` folds lint + page metadata into one JSON for the skill to read; the skill decides what to merge/delete and writes a proposal file; `gc-apply` validates the *whole* proposal first (slugs exist, git-tracked, no self-merge) then executes under the existing wiki lock, regenerating the index and appending the log. git tracking is forced as the recovery path; the core executes but never commits. Two-phase (validate-all-first) makes partial apply impossible.

**Tech Stack:** Python 3.10+ (system 3.12 editable install; tests run via `python -m pytest`), argparse subparsers, pytest (`tmp_path`/`capsys`/`monkeypatch`), `subprocess` for the git-tracking check, `fcntl` lock (existing `with_wiki_lock`).

---

## Design reference

Spec: `docs/superpowers/specs/2026-06-06-omx-wiki-gc-design.md` (committed `3690e3a`).

## File Structure

| File | Responsibility | Action |
|:---|:---|:---|
| `omx-core/omx_core/wiki/gc.py` | NEW module: `GcPlan` type, `parse_gc_proposal`, `is_git_tracked`, `delete_page`, `merge_pages`, `apply_gc` | Create |
| `omx-core/omx_core/cli.py` | Add `_cmd_wiki_gc` (read-only) + `_cmd_wiki_gc_apply` handlers and their subparsers | Modify |
| `omx-core/tests/test_wiki_gc.py` | Unit tests for the gc module (parser, delete, merge, two-phase, git check) | Create |
| `omx-core/tests/test_cli.py` | CLI end-to-end tests for `wiki gc` + `wiki gc-apply` | Modify (append) |
| `skills/exp-analyze/SKILL.md` | Short "wiki maintenance" guidance: gc -> read -> propose -> human gate -> gc-apply | Modify |
| `.claude-plugin/plugin.json` | version 0.1.6 -> 0.1.7 | Modify |
| `CHANGELOG.md` | `[0.1.7]` Added entry | Modify |

## Conventions the worker must follow

- **Run any single test:** `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py::<name> -v`
- **Full suite:** `cd /root/oh-my-experiments/omx-core && python -m pytest -q` (baseline before this plan: 387 passed, 1 skipped).
- **Imports in gc.py:** `from omx_core.omx_paths import OmxPaths, OmxError, atomic_path` and `from omx_core.wiki import storage` and `from omx_core.wiki.types import WikiError`. Wiki loud-fails raise `WikiError` (subclass of `OmxError`); the CLI catches `OmxError`.
- **Timestamps:** never call a wall clock inside gc.py — callers inject `now` (a naive ISO string), exactly like `storage`/`ingest`/`lint`. The CLI passes `_now_iso()`.
- **Slug normalization:** slugs may arrive with or without the trailing `.md`; `storage.read_page`/`write_page`/`wiki_page` already tolerate both. `list_pages` returns names *with* `.md`. Normalize to *with* `.md` form inside gc for comparison (helper below).
- **Locking:** `delete_page` and `merge_pages` assume the caller already holds the wiki lock (same contract as `update_index`/`append_log`). Only `apply_gc` takes the lock, via `storage.with_wiki_lock`.
- **No `git add -A`** in any commit step — stage the exact paths shown.

---

### Task 1: gc module skeleton + `GcPlan` type + slug normalizer

**Files:**
- Create: `omx-core/omx_core/wiki/gc.py`
- Test: `omx-core/tests/test_wiki_gc.py`

- [ ] **Step 1: Write the failing test**

Create `omx-core/tests/test_wiki_gc.py`:

```python
"""Tests for omx_core.wiki.gc — wiki garbage-collect (delete/merge) execution."""
from omx_core.wiki import gc


def test_norm_slug_adds_md_suffix():
    assert gc._norm_slug("foo") == "foo.md"
    assert gc._norm_slug("foo.md") == "foo.md"


def test_gcplan_defaults_are_empty():
    plan = gc.GcPlan()
    assert plan.deletes == []
    assert plan.merges == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.wiki.gc'`

- [ ] **Step 3: Write minimal implementation**

Create `omx-core/omx_core/wiki/gc.py`:

```python
"""omx_core.wiki.gc — execute approved wiki delete/merge (two-phase, git-guarded).

The core carries ZERO semantic judgment (INV-1): it executes an already-approved
proposal file. `parse_gc_proposal` turns the proposal markdown into a GcPlan;
`apply_gc` validates the WHOLE plan (slugs exist, git-tracked, no self-merge)
before mutating anything, so a partial apply is impossible. git tracking is the
recovery path — an untracked target loud-fails rather than becoming unrecoverable.
Wall-clock `now` is injected (no clock here), matching storage/ingest/lint.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from omx_core.omx_paths import OmxPaths, OmxError
from omx_core.wiki import storage
from omx_core.wiki.types import WikiError, WikiPage, WIKI_SCHEMA_VERSION


def _norm_slug(slug: str) -> str:
    """Normalize a slug to its '<name>.md' form (list_pages/merge compare on this)."""
    return slug if slug.endswith(".md") else f"{slug}.md"


@dataclass
class GcPlan:
    """A parsed, not-yet-validated gc proposal."""
    deletes: list = field(default_factory=list)          # list[str] slug
    merges: list = field(default_factory=list)           # list[dict] {into:str, from:list[str]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd /root/oh-my-experiments
git add omx-core/omx_core/wiki/gc.py omx-core/tests/test_wiki_gc.py
git commit -m "feat(wiki-gc): module skeleton + GcPlan type + slug normalizer"
```

---

### Task 2: `parse_gc_proposal` — the skill<->core contract parser

**Files:**
- Modify: `omx-core/omx_core/wiki/gc.py`
- Test: `omx-core/tests/test_wiki_gc.py`

The proposal format (from the spec):

```markdown
---
kind: wiki-gc
generated: 2026-06-06T10:30:00
root: .
---

## DELETE

- slug: old_page.md
  reason: superseded

## MERGE

- into: survivor.md
  from:
    - dup_a.md
    - dup_b.md
  reason: one topic
```

Parser rules: `kind: wiki-gc` required (else loud-fail); `## DELETE` items are `- slug: X`; `## MERGE` items are `- into: X` followed by an indented `from:` list. `reason:` lines are ignored by the parser (human-only). An empty proposal yields an empty plan. A `## MERGE` item whose `into` appears in its own `from` is left for `apply_gc` to reject (parser stays structural). Malformed frontmatter or a `kind` mismatch loud-fails here.

- [ ] **Step 1: Write the failing test**

Append to `omx-core/tests/test_wiki_gc.py`:

```python
import pytest
from omx_core.omx_paths import OmxError

_VALID_PROPOSAL = """---
kind: wiki-gc
generated: 2026-06-06T10:30:00
root: .
---

## DELETE

- slug: old_page.md
  reason: superseded by newer

## MERGE

- into: survivor.md
  from:
    - dup_a.md
    - dup_b.md
  reason: one topic
"""


def test_parse_proposal_extracts_deletes_and_merges():
    plan = gc.parse_gc_proposal(_VALID_PROPOSAL)
    assert plan.deletes == ["old_page.md"]
    assert plan.merges == [{"into": "survivor.md", "from": ["dup_a.md", "dup_b.md"]}]


def test_parse_proposal_empty_sections_yield_empty_plan():
    raw = "---\nkind: wiki-gc\n---\n\n## DELETE\n\n## MERGE\n"
    plan = gc.parse_gc_proposal(raw)
    assert plan.deletes == []
    assert plan.merges == []


def test_parse_proposal_bad_kind_loud_fails():
    raw = "---\nkind: something-else\n---\n## DELETE\n- slug: x.md\n"
    with pytest.raises(OmxError):
        gc.parse_gc_proposal(raw)


def test_parse_proposal_missing_frontmatter_loud_fails():
    with pytest.raises(OmxError):
        gc.parse_gc_proposal("## DELETE\n- slug: x.md\n")


def test_parse_proposal_normalizes_bare_slugs():
    raw = "---\nkind: wiki-gc\n---\n## DELETE\n- slug: bare\n## MERGE\n- into: s\n  from:\n    - f1\n"
    plan = gc.parse_gc_proposal(raw)
    assert plan.deletes == ["bare.md"]
    assert plan.merges == [{"into": "s.md", "from": ["f1.md"]}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py -k parse -v`
Expected: FAIL — `AttributeError: module 'omx_core.wiki.gc' has no attribute 'parse_gc_proposal'`

- [ ] **Step 3: Write minimal implementation**

Add to `omx-core/omx_core/wiki/gc.py`:

```python
import re

_FM_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


def parse_gc_proposal(raw: str) -> GcPlan:
    """Parse a wiki-gc proposal markdown into a GcPlan. Loud-fail on a missing
    '---' frontmatter block or a `kind` other than 'wiki-gc'. Structural only —
    self-merge and missing-slug checks happen in apply_gc."""
    normalized = raw.replace("\r\n", "\n")
    m = _FM_RE.match(normalized)
    if not m:
        raise WikiError("gc proposal has no '---' frontmatter block")
    fm, body = m.group(1), m.group(2)
    kind = None
    for line in fm.split("\n"):
        if line.startswith("kind:"):
            kind = line.split(":", 1)[1].strip()
            break
    if kind != "wiki-gc":
        raise WikiError(f"gc proposal kind must be 'wiki-gc', got {kind!r}")

    deletes: list = []
    merges: list = []
    section = None
    current = None  # the in-progress merge dict
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped == "## DELETE":
            section, current = "delete", None
            continue
        if stripped == "## MERGE":
            section, current = "merge", None
            continue
        if section == "delete":
            mm = re.match(r"-\s*slug:\s*(\S+)", stripped)
            if mm:
                deletes.append(_norm_slug(mm.group(1)))
        elif section == "merge":
            mi = re.match(r"-\s*into:\s*(\S+)", stripped)
            if mi:
                current = {"into": _norm_slug(mi.group(1)), "from": []}
                merges.append(current)
                continue
            mf = re.match(r"-\s*(\S+)", stripped)
            # an indented "- <slug>" under a "from:" belongs to the current merge;
            # the literal "from:" line itself has no leading "-", so it's skipped
            if current is not None and mf and not stripped.startswith("from:") \
                    and "into:" not in stripped and "reason:" not in stripped:
                current["from"].append(_norm_slug(mf.group(1)))
    return GcPlan(deletes=deletes, merges=merges)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py -k parse -v`
Expected: PASS (5 parse tests)

- [ ] **Step 5: Commit**

```bash
cd /root/oh-my-experiments
git add omx-core/omx_core/wiki/gc.py omx-core/tests/test_wiki_gc.py
git commit -m "feat(wiki-gc): parse_gc_proposal (kind-guarded, slug-normalizing)"
```

---

### Task 3: `is_git_tracked` — the recovery guard

**Files:**
- Modify: `omx-core/omx_core/wiki/gc.py`
- Test: `omx-core/tests/test_wiki_gc.py`

`is_git_tracked(repo_root, file_path)` returns True iff `git -C <repo_root> ls-files --error-unmatch <file_path>` exits 0. No git / not a repo / untracked all return False (never raise — the *caller* decides the loud-fail message). Use `subprocess.run` with captured output and `check=False`.

- [ ] **Step 1: Write the failing test**

Append to `omx-core/tests/test_wiki_gc.py`:

```python
import subprocess


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


def test_is_git_tracked_true_for_committed_file(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    f = tmp_path / "a.txt"
    f.write_text("hi", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-m", "x")
    assert gc.is_git_tracked(tmp_path, f) is True


def test_is_git_tracked_false_for_untracked_file(tmp_path):
    _git(tmp_path, "init")
    f = tmp_path / "b.txt"
    f.write_text("hi", encoding="utf-8")
    assert gc.is_git_tracked(tmp_path, f) is False


def test_is_git_tracked_false_when_no_repo(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("hi", encoding="utf-8")
    assert gc.is_git_tracked(tmp_path, f) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py -k git_tracked -v`
Expected: FAIL — `AttributeError: ... has no attribute 'is_git_tracked'`

- [ ] **Step 3: Write minimal implementation**

Add to `omx-core/omx_core/wiki/gc.py` (add `import subprocess` and `from pathlib import Path` at top):

```python
import subprocess
from pathlib import Path


def is_git_tracked(repo_root, file_path) -> bool:
    """True iff `file_path` is a git-tracked file under `repo_root`. No git, no
    repo, or an untracked path all return False (never raises) — the caller turns
    a False into the loud-fail. This is the recovery guarantee: gc-apply refuses
    to delete anything git cannot restore."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", str(Path(file_path).resolve())],
            capture_output=True, text=True, check=False,
        )
    except (FileNotFoundError, OSError):
        return False
    return proc.returncode == 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py -k git_tracked -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd /root/oh-my-experiments
git add omx-core/omx_core/wiki/gc.py omx-core/tests/test_wiki_gc.py
git commit -m "feat(wiki-gc): is_git_tracked recovery guard (subprocess git ls-files)"
```

---

### Task 4: `delete_page` — single-page delete primitive

**Files:**
- Modify: `omx-core/omx_core/wiki/gc.py`
- Test: `omx-core/tests/test_wiki_gc.py`

`delete_page(paths, slug)` unlinks the page file. It does NOT take the lock or update the index (the caller `apply_gc` does, once, for the whole batch). It loud-fails if the slug is a reserved file or does not exist (the latter shouldn't happen — apply_gc pre-validates — but the primitive defends itself). It does NOT do the git check (apply_gc does that across the whole plan before any mutation).

- [ ] **Step 1: Write the failing test**

Append to `omx-core/tests/test_wiki_gc.py`:

```python
from omx_core.omx_paths import OmxPaths


def _seed_page(tmp_path, title, content="body text", category="reference"):
    """Create one wiki page via ingest, return its slug."""
    from omx_core.wiki import ingest
    res = ingest.ingest_knowledge(
        OmxPaths(root=tmp_path), now="2026-06-06T00:00:00",
        title=title, content=content, tags=["t"], category=category,
        confidence="medium", sources=[])
    return res["slug"]


def test_delete_page_removes_file(tmp_path):
    slug = _seed_page(tmp_path, "Doomed Page")
    paths = OmxPaths(root=tmp_path)
    assert paths.wiki_page(slug[:-3]).exists()
    gc.delete_page(paths, slug)
    assert not paths.wiki_page(slug[:-3]).exists()


def test_delete_page_missing_loud_fails(tmp_path):
    paths = OmxPaths(root=tmp_path)
    paths.wiki_dir().mkdir(parents=True, exist_ok=True)
    with pytest.raises(OmxError):
        gc.delete_page(paths, "ghost.md")


def test_delete_page_reserved_loud_fails(tmp_path):
    paths = OmxPaths(root=tmp_path)
    paths.wiki_dir().mkdir(parents=True, exist_ok=True)
    with pytest.raises(OmxError):
        gc.delete_page(paths, "index.md")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py -k delete_page -v`
Expected: FAIL — `AttributeError: ... has no attribute 'delete_page'`

- [ ] **Step 3: Write minimal implementation**

Add to `omx-core/omx_core/wiki/gc.py` (add `from omx_core.wiki.types import RESERVED_FILES` to the existing types import):

```python
def delete_page(paths: OmxPaths, slug: str) -> None:
    """Unlink one wiki page. Caller MUST hold the wiki lock and is responsible for
    update_index/append_log afterwards (apply_gc batches these). Loud-fail on a
    reserved file or an absent page. No git check here — apply_gc validates the
    whole plan against git before any mutation."""
    norm = _norm_slug(slug)
    if norm in RESERVED_FILES:
        raise WikiError(f"cannot delete reserved file {norm!r}")
    fp = paths.wiki_page(norm[:-3])  # validates token -> blocks traversal
    if not fp.exists():
        raise WikiError(f"cannot delete absent page {norm!r}")
    fp.unlink()
```

Update the types import line to:

```python
from omx_core.wiki.types import WikiError, WikiPage, WIKI_SCHEMA_VERSION, RESERVED_FILES
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py -k delete_page -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd /root/oh-my-experiments
git add omx-core/omx_core/wiki/gc.py omx-core/tests/test_wiki_gc.py
git commit -m "feat(wiki-gc): delete_page primitive (reserved/absent loud-fail)"
```

---

### Task 5: `merge_pages` — lossless append-merge primitive

**Files:**
- Modify: `omx-core/omx_core/wiki/gc.py`
- Test: `omx-core/tests/test_wiki_gc.py`

`merge_pages(paths, into, from_slugs, now)` folds each `from` page into the `into` page (the survivor), then deletes the `from` pages. Lossless (INV-2): the survivor's content gains a `## Merged from <slug> (<now>)` section per source, tags union, sources append, links union, confidence max. Caller holds the lock; caller does index/log. Loud-fail if `into` is in `from_slugs` (self-merge) or any page is absent.

Confidence-max uses the same rank table as ingest: `{"high": 3, "medium": 2, "low": 1}`.

- [ ] **Step 1: Write the failing test**

Append to `omx-core/tests/test_wiki_gc.py`:

```python
def test_merge_pages_survivor_gains_content_and_deletes_sources(tmp_path):
    into = _seed_page(tmp_path, "Survivor", content="survivor body")
    src = _seed_page(tmp_path, "Source One", content="source body unique-marker")
    paths = OmxPaths(root=tmp_path)
    gc.merge_pages(paths, into=into, from_slugs=[src], now="2026-06-06T01:00:00")
    # source gone
    assert not paths.wiki_page(src[:-3]).exists()
    # survivor still there and now contains the source's body
    page = storage.read_page(paths, into)
    assert "unique-marker" in page.content
    assert "Merged from" in page.content


def test_merge_pages_unions_tags_and_takes_max_confidence(tmp_path):
    from omx_core.wiki import ingest
    paths = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(paths, now="2026-06-06T00:00:00", title="Into Page",
                            content="x", tags=["a"], category="reference",
                            confidence="low", sources=["s1"])
    ingest.ingest_knowledge(paths, now="2026-06-06T00:00:00", title="From Page",
                            content="y", tags=["b"], category="reference",
                            confidence="high", sources=["s2"])
    gc.merge_pages(paths, into="into_page.md", from_slugs=["from_page.md"],
                   now="2026-06-06T01:00:00")
    page = storage.read_page(paths, "into_page.md")
    assert set(page.tags) == {"a", "b"}
    assert page.confidence == "high"           # max(low, high)
    assert set(page.sources) == {"s1", "s2"}


def test_merge_pages_self_merge_loud_fails(tmp_path):
    into = _seed_page(tmp_path, "Selfie")
    paths = OmxPaths(root=tmp_path)
    with pytest.raises(OmxError):
        gc.merge_pages(paths, into=into, from_slugs=[into], now="2026-06-06T01:00:00")


def test_merge_pages_absent_source_loud_fails(tmp_path):
    into = _seed_page(tmp_path, "Survivor Two")
    paths = OmxPaths(root=tmp_path)
    with pytest.raises(OmxError):
        gc.merge_pages(paths, into=into, from_slugs=["ghost.md"], now="2026-06-06T01:00:00")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py -k merge_pages -v`
Expected: FAIL — `AttributeError: ... has no attribute 'merge_pages'`

- [ ] **Step 3: Write minimal implementation**

Add to `omx-core/omx_core/wiki/gc.py`:

```python
_CONF_RANK = {"high": 3, "medium": 2, "low": 1}


def merge_pages(paths: OmxPaths, *, into: str, from_slugs: list, now: str) -> None:
    """Fold each `from` page into the `into` survivor (lossless), then delete the
    `from` pages. Tags union, sources append, links union, confidence max; each
    source body is appended as a '## Merged from <slug> (<now>)' section. Caller
    holds the lock and does update_index/append_log. Loud-fail on self-merge or an
    absent page."""
    into_norm = _norm_slug(into)
    froms = [_norm_slug(s) for s in from_slugs]
    if into_norm in froms:
        raise WikiError(f"self-merge: {into_norm!r} is both survivor and source")

    survivor = storage.read_page(paths, into_norm)
    if survivor is None:
        raise WikiError(f"merge survivor {into_norm!r} does not exist")

    tags = list(survivor.tags)
    sources = list(survivor.sources)
    links = list(survivor.links)
    confidence = survivor.confidence
    content = survivor.content.rstrip()

    for fslug in froms:
        src = storage.read_page(paths, fslug)
        if src is None:
            raise WikiError(f"merge source {fslug!r} does not exist")
        for t in src.tags:
            if t not in tags:
                tags.append(t)
        for s in src.sources:
            if s not in sources:
                sources.append(s)
        for l in src.links:
            if l not in links:
                links.append(l)
        if _CONF_RANK.get(src.confidence, 2) > _CONF_RANK.get(confidence, 2):
            confidence = src.confidence
        content += f"\n\n---\n\n## Merged from {fslug} ({now})\n\n{src.content.strip()}\n"

    merged = WikiPage(
        slug=into_norm, title=survivor.title, tags=tags,
        created=survivor.created, updated=now, sources=sources, links=links,
        category=survivor.category, confidence=confidence,
        schema_version=survivor.schema_version, content=content,
    )
    storage.write_page(paths, merged, now=now)
    for fslug in froms:
        delete_page(paths, fslug)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py -k merge_pages -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd /root/oh-my-experiments
git add omx-core/omx_core/wiki/gc.py omx-core/tests/test_wiki_gc.py
git commit -m "feat(wiki-gc): merge_pages lossless append-merge primitive"
```

---

### Task 6: `apply_gc` — two-phase, git-guarded, lock-wrapped execution

**Files:**
- Modify: `omx-core/omx_core/wiki/gc.py`
- Test: `omx-core/tests/test_wiki_gc.py`

`apply_gc(paths, plan, *, now, repo_root, git_check=is_git_tracked)` is the heart. **Phase 1 (validate, no mutation):** every delete slug and every merge `into`+`from` slug must (a) exist as a page file and (b) be git-tracked via `git_check`; no merge may be a self-merge. Any failure raises `WikiError` and **nothing is touched**. **Phase 2:** under `storage.with_wiki_lock`, run all deletes then all merges, then `storage.update_index` + `storage.append_log`. Returns `{"deleted": [...], "merged": [{"into":..., "from":[...]}]}`.

`git_check` is injected so tests can pass a stub; the CLI passes the real `is_git_tracked`. An empty plan returns `{"deleted": [], "merged": []}` without taking the lock.

- [ ] **Step 1: Write the failing test**

Append to `omx-core/tests/test_wiki_gc.py`:

```python
def _always_tracked(repo_root, file_path):
    return True


def _never_tracked(repo_root, file_path):
    return False


def test_apply_gc_deletes_and_merges_when_tracked(tmp_path):
    paths = OmxPaths(root=tmp_path)
    doomed = _seed_page(tmp_path, "Doomed")
    into = _seed_page(tmp_path, "Keeper", content="keeper body")
    src = _seed_page(tmp_path, "Dup", content="dup unique-xyz")
    plan = gc.GcPlan(deletes=[doomed], merges=[{"into": into, "from": [src]}])
    res = gc.apply_gc(paths, plan, now="2026-06-06T02:00:00",
                      repo_root=tmp_path, git_check=_always_tracked)
    assert res == {"deleted": [doomed], "merged": [{"into": into, "from": [src]}]}
    assert not paths.wiki_page(doomed[:-3]).exists()
    assert not paths.wiki_page(src[:-3]).exists()
    assert "unique-xyz" in storage.read_page(paths, into).content


def test_apply_gc_untracked_aborts_with_zero_changes(tmp_path):
    paths = OmxPaths(root=tmp_path)
    doomed = _seed_page(tmp_path, "Doomed Two")
    plan = gc.GcPlan(deletes=[doomed])
    with pytest.raises(OmxError):
        gc.apply_gc(paths, plan, now="2026-06-06T02:00:00",
                    repo_root=tmp_path, git_check=_never_tracked)
    # the critical regression: nothing was deleted
    assert paths.wiki_page(doomed[:-3]).exists()


def test_apply_gc_missing_slug_aborts_with_zero_changes(tmp_path):
    paths = OmxPaths(root=tmp_path)
    keep = _seed_page(tmp_path, "Innocent")
    plan = gc.GcPlan(deletes=["ghost.md", keep])
    with pytest.raises(OmxError):
        gc.apply_gc(paths, plan, now="2026-06-06T02:00:00",
                    repo_root=tmp_path, git_check=_always_tracked)
    # the innocent page that came AFTER the bad one must survive (validate-first)
    assert paths.wiki_page(keep[:-3]).exists()


def test_apply_gc_self_merge_aborts(tmp_path):
    paths = OmxPaths(root=tmp_path)
    s = _seed_page(tmp_path, "Selfish")
    plan = gc.GcPlan(merges=[{"into": s, "from": [s]}])
    with pytest.raises(OmxError):
        gc.apply_gc(paths, plan, now="2026-06-06T02:00:00",
                    repo_root=tmp_path, git_check=_always_tracked)
    assert paths.wiki_page(s[:-3]).exists()


def test_apply_gc_empty_plan_is_noop(tmp_path):
    paths = OmxPaths(root=tmp_path)
    _seed_page(tmp_path, "Untouched")
    res = gc.apply_gc(paths, gc.GcPlan(), now="2026-06-06T02:00:00",
                      repo_root=tmp_path, git_check=_never_tracked)
    assert res == {"deleted": [], "merged": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py -k apply_gc -v`
Expected: FAIL — `AttributeError: ... has no attribute 'apply_gc'`

- [ ] **Step 3: Write minimal implementation**

Add to `omx-core/omx_core/wiki/gc.py`:

```python
def apply_gc(paths: OmxPaths, plan: GcPlan, *, now: str, repo_root,
             git_check=is_git_tracked) -> dict:
    """Two-phase apply. Phase 1 validates the WHOLE plan (every slug exists and is
    git-tracked; no self-merge) and mutates nothing on failure. Phase 2, under the
    wiki lock, runs deletes then merges, then regenerates the index and logs. An
    empty plan is a no-op (no lock). git_check is injected for testing; the CLI
    passes is_git_tracked. The validate-first design makes a partial apply
    impossible — the recovery guarantee plus atomicity of intent."""
    if not plan.deletes and not plan.merges:
        return {"deleted": [], "merged": []}

    # ---- phase 1: validate everything, touch nothing ----
    def _require(slug: str) -> None:
        norm = _norm_slug(slug)
        fp = paths.wiki_page(norm[:-3])
        if not fp.exists():
            raise WikiError(f"gc target {norm!r} does not exist")
        if not git_check(repo_root, fp):
            raise WikiError(
                f"wiki gc-apply requires git tracking for recovery; {norm!r} is untracked")

    for slug in plan.deletes:
        _require(slug)
    for merge in plan.merges:
        into_norm = _norm_slug(merge["into"])
        froms = [_norm_slug(s) for s in merge["from"]]
        if into_norm in froms:
            raise WikiError(f"self-merge: {into_norm!r} is both survivor and source")
        _require(into_norm)
        for f in froms:
            _require(f)

    # ---- phase 2: execute under the lock ----
    def _do() -> dict:
        for slug in plan.deletes:
            delete_page(paths, slug)
        for merge in plan.merges:
            merge_pages(paths, into=merge["into"], from_slugs=merge["from"], now=now)
        storage.update_index(paths, now=now)
        n_del = len(plan.deletes)
        n_merge = sum(len(m["from"]) for m in plan.merges)
        storage.append_log(paths, now=now, operation="gc-apply",
                           pages=[_norm_slug(s) for s in plan.deletes],
                           summary=f"deleted {n_del}, merged {n_merge} source(s)")
        return {
            "deleted": [_norm_slug(s) for s in plan.deletes],
            "merged": [{"into": _norm_slug(m["into"]),
                        "from": [_norm_slug(s) for s in m["from"]]} for m in plan.merges],
        }

    return storage.with_wiki_lock(paths, _do)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py -k apply_gc -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the whole gc module test file**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_wiki_gc.py -v`
Expected: PASS (all gc tests; ~22)

- [ ] **Step 6: Commit**

```bash
cd /root/oh-my-experiments
git add omx-core/omx_core/wiki/gc.py omx-core/tests/test_wiki_gc.py
git commit -m "feat(wiki-gc): apply_gc two-phase git-guarded lock-wrapped execution"
```

---

### Task 7: CLI `wiki gc` (read-only diagnosis) + `wiki gc-apply`

**Files:**
- Modify: `omx-core/omx_core/cli.py` (add two handlers after `_cmd_wiki_read` at line 394; add two subparsers after the `read` registration which ends at line 525)
- Test: `omx-core/tests/test_cli.py` (append)

`wiki gc --root <r>` is read-only: it prints `{"lint": <lint result>, "pages": [{slug, title, category, updated, bytes}]}`. `wiki gc-apply --proposal <f> --root <r>` reads the proposal file, parses it, and calls `apply_gc` with `repo_root=args.root`; prints `{"deleted":[...], "merged":[...]}`. Both catch `OmxError` -> `SystemExit` (the established CLI pattern).

- [ ] **Step 1: Write the failing test**

Append to `omx-core/tests/test_cli.py`:

```python
def test_wiki_gc_readonly_emits_lint_and_pages(tmp_path, capsys):
    from omx_core.cli import main
    from omx_core.wiki import ingest
    from omx_core.omx_paths import OmxPaths
    ingest.ingest_knowledge(OmxPaths(root=tmp_path), now="2026-06-06T00:00:00",
                            title="Page A", content="aaa", tags=["t"],
                            category="reference", confidence="medium", sources=[])
    rc = main(["wiki", "gc", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "lint" in out and "pages" in out
    assert out["pages"][0]["slug"] == "page_a.md"
    assert "bytes" in out["pages"][0]


def test_wiki_gc_apply_deletes_via_proposal(tmp_path, capsys):
    import subprocess
    from omx_core.cli import main
    from omx_core.wiki import ingest
    from omx_core.omx_paths import OmxPaths
    paths = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(paths, now="2026-06-06T00:00:00", title="Trash Me",
                            content="junk", tags=["t"], category="reference",
                            confidence="medium", sources=[])
    # make it git-tracked so the recovery guard passes
    for args in (["init"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
                 ["add", "-A"], ["commit", "-m", "seed"]):
        subprocess.run(["git", *args], cwd=str(tmp_path), check=True, capture_output=True, text=True)
    proposal = tmp_path / "p.md"
    proposal.write_text(
        "---\nkind: wiki-gc\n---\n\n## DELETE\n\n- slug: trash_me.md\n  reason: junk\n\n## MERGE\n",
        encoding="utf-8")
    rc = main(["wiki", "gc-apply", "--proposal", str(proposal), "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["deleted"] == ["trash_me.md"]
    assert not paths.wiki_page("trash_me").exists()


def test_wiki_gc_apply_untracked_loud_fails(tmp_path, capsys):
    import pytest
    from omx_core.cli import main
    from omx_core.wiki import ingest
    from omx_core.omx_paths import OmxPaths
    paths = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(paths, now="2026-06-06T00:00:00", title="Untracked",
                            content="x", tags=["t"], category="reference",
                            confidence="medium", sources=[])
    proposal = tmp_path / "p.md"
    proposal.write_text("---\nkind: wiki-gc\n---\n## DELETE\n- slug: untracked.md\n", encoding="utf-8")
    # no git init -> untracked -> must loud-fail and NOT delete
    with pytest.raises(SystemExit):
        main(["wiki", "gc-apply", "--proposal", str(proposal), "--root", str(tmp_path)])
    assert paths.wiki_page("untracked").exists()
```

Note: `test_cli.py` imports `pytest` *inside each function* (local import), not at module top — the v0.1.6 wiki-read tests follow this. So the `test_wiki_gc_apply_untracked_loud_fails` test above puts `import pytest` as its first line (already shown). The two tests that don't use `pytest.raises` need no import.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_cli.py -k wiki_gc -v`
Expected: FAIL — argparse error (`invalid choice: 'gc'`) / SystemExit from unknown subcommand

- [ ] **Step 3: Write minimal implementation**

In `omx-core/omx_core/cli.py`, add the gc import to the existing wiki import line (line 31):

```python
from omx_core.wiki import ingest as _wiki_ingest, query as _wiki_query, lint as _wiki_lint, storage as _wiki_storage, gc as _wiki_gc
```

Add two handlers immediately after `_cmd_wiki_read` (after line 394):

```python
def _cmd_wiki_gc(args) -> int:
    """Read-only gc diagnosis: lint result + page metadata, as one JSON object for
    the skill to read. Touches nothing (the skill judges, gc-apply executes)."""
    paths = OmxPaths(root=args.root)
    try:
        lint_res = _wiki_lint.lint_wiki(paths, now=_now_iso(),
                                        stale_days=args.stale_days,
                                        max_page_size=args.max_page_size)
    except OmxError as e:
        raise SystemExit(str(e))
    pages = []
    for slug in _wiki_storage.list_pages(paths):
        try:
            page = _wiki_storage.read_page(paths, slug)
        except OmxError:
            continue
        if page is None:
            continue
        pages.append({
            "slug": slug, "title": page.title, "category": page.category,
            "updated": page.updated,
            "bytes": len(page.content.encode("utf-8")),
        })
    print(json.dumps({"lint": lint_res, "pages": pages}))
    return 0


def _cmd_wiki_gc_apply(args) -> int:
    """Parse an approved proposal and two-phase apply it (validate-all, then execute
    under the lock). git tracking is enforced by apply_gc as the recovery path."""
    proposal = Path(args.proposal)
    if not proposal.exists():
        raise SystemExit(f"proposal not found: {proposal}")
    paths = OmxPaths(root=args.root)
    try:
        plan = _wiki_gc.parse_gc_proposal(proposal.read_text(encoding="utf-8"))
        res = _wiki_gc.apply_gc(paths, plan, now=_now_iso(), repo_root=args.root)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(res))
    return 0
```

Add two subparsers after the `read` registration (after line 525, `pwr.set_defaults(func=_cmd_wiki_read)`, before `return p`):

```python
    pwg = wsub.add_parser("gc", help="read-only gc diagnosis (lint + page metadata as JSON)")
    pwg.add_argument("--root", required=True)
    pwg.add_argument("--stale-days", type=int, default=30, dest="stale_days")
    pwg.add_argument("--max-page-size", type=int, default=10240, dest="max_page_size")
    pwg.set_defaults(func=_cmd_wiki_gc)

    pwga = wsub.add_parser("gc-apply",
                           help="apply an approved wiki-gc proposal (two-phase, git-guarded)")
    pwga.add_argument("--root", required=True)
    pwga.add_argument("--proposal", required=True, help="path to the approved wiki-gc proposal .md")
    pwga.set_defaults(func=_cmd_wiki_gc_apply)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest tests/test_cli.py -k wiki_gc -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd /root/oh-my-experiments
git add omx-core/omx_core/cli.py omx-core/tests/test_cli.py
git commit -m "feat(wiki-gc): CLI verbs wiki gc (read-only) + wiki gc-apply (two-phase)"
```

---

### Task 8: Skill guidance — wiki maintenance flow in exp-analyze

**Files:**
- Modify: `skills/exp-analyze/SKILL.md`

Add a short "Wiki maintenance (gc)" subsection so the skill (Claude) knows the flow. The core does the mechanism; the skill does the semantic judgment. This is prose, not code — no test.

- [ ] **Step 1: Locate the wiki section in the skill**

Run: `grep -n "wiki" /root/oh-my-experiments/skills/exp-analyze/SKILL.md | head`
Find the existing wiki guidance (query/add/lint). The new subsection goes right after it.

- [ ] **Step 2: Add the subsection**

Insert after the existing wiki guidance block:

```markdown
### Wiki maintenance (gc)

When the wiki accumulates overlapping or superseded pages, consolidate it — but
the core never decides *what* to remove; you do, and a human approves.

1. `omx wiki gc --root <r>` — read-only. Returns `{lint, pages:[{slug,title,category,updated,bytes}]}`.
2. For each merge/delete candidate, `omx wiki read --slug <slug> --root <r>` to read the
   FULL body. lint catches mechanical signals (orphan/stale/oversized); only reading the
   bodies reveals *semantic* duplicates (two pages that are one topic, a later page that
   supersedes an earlier one).
3. Write a proposal `proposals/<ts>-wiki-gc.md` with `---\nkind: wiki-gc\n---` frontmatter,
   a `## DELETE` section (`- slug: X` + `reason:`), and a `## MERGE` section
   (`- into: X` / `from:` list + `reason:`). Each item carries a one-line reason.
4. STOP. The user reviews the proposal and deletes any line they disagree with —
   editing the file IS the approval. Never apply without this human gate.
5. `omx wiki gc-apply --proposal <file> --root <r>` — two-phase: validates the whole
   proposal (slugs exist, git-tracked, no self-merge) then executes under the wiki lock.
   It REFUSES to touch any page git does not track (so `git restore` always recovers).
   The core executes but does not commit — commit the result yourself after review.

Never hand-delete or hand-merge wiki pages with Edit/Write/rm: that bypasses the lock,
the index regeneration, the append-log, and the git-recovery guard.
```

- [ ] **Step 3: Verify the skill file is coherent**

Run: `grep -n "gc-apply\|wiki gc\|Wiki maintenance" /root/oh-my-experiments/skills/exp-analyze/SKILL.md`
Expected: the new subsection lines appear.

- [ ] **Step 4: Commit**

```bash
cd /root/oh-my-experiments
git add skills/exp-analyze/SKILL.md
git commit -m "docs(exp-analyze): wiki maintenance (gc) flow guidance"
```

---

### Task 9: Release — version bump + CHANGELOG + full suite

**Files:**
- Modify: `.claude-plugin/plugin.json` (`0.1.6` -> `0.1.7`)
- Modify: `CHANGELOG.md` (new `[0.1.7]` section)

- [ ] **Step 1: Bump the plugin version**

Edit `.claude-plugin/plugin.json`: change `"version": "0.1.6"` to `"version": "0.1.7"`.

- [ ] **Step 2: Add the CHANGELOG entry**

Insert at the top of the version list in `CHANGELOG.md` (above `## [0.1.6]`):

```markdown
## [0.1.7] - 2026-06-06

A wiki maintenance feature: consolidate / delete superseded or overlapping wiki
pages under a human gate, with git as the recovery path. The core carries no
semantic judgment — it diagnoses and executes; the skill (Claude) decides what to
merge or delete and a human approves the proposal.

### Added

- **`omx wiki gc`** (read-only). Folds `lint` (orphan/stale/broken-ref/oversized)
  and per-page metadata (slug, title, category, updated, bytes) into one JSON
  object for the skill to read. Touches nothing.
- **`omx wiki gc-apply --proposal <file>`** (two-phase, git-guarded). Parses an
  approved `kind: wiki-gc` proposal (`## DELETE` / `## MERGE` sections), then in a
  single validate-all-first pass confirms every target page exists, is git-tracked,
  and that no merge is a self-merge; only then, under the wiki lock, runs the
  deletes and merges, regenerates the index, and appends the log. A validation
  failure leaves the wiki byte-for-byte unchanged (partial apply is impossible),
  and an untracked target loud-fails (so `git restore` always recovers). Merges are
  lossless: the survivor gains each source's body as a `## Merged from <slug>`
  section, with tags/sources/links unioned and confidence taken as the max. The
  core executes but never commits.
- New core module `omx_core/wiki/gc.py` (`parse_gc_proposal`, `is_git_tracked`,
  `delete_page`, `merge_pages`, `apply_gc`) and exp-analyze skill guidance for the
  gc -> read -> propose -> human-gate -> gc-apply flow.
```

- [ ] **Step 3: Run the FULL suite (fresh verification evidence)**

Run: `cd /root/oh-my-experiments/omx-core && python -m pytest -q`
Expected: all pass (baseline 387 passed + 1 skipped, plus the new gc tests — ~22 gc-module + 3 CLI = ~25 new; target ~412 passed, 1 skipped). Read the actual count; if anything fails, fix before committing.

- [ ] **Step 4: Smoke-test the real verbs end-to-end**

Run (against a throwaway tmp wiki, not the live one):

```bash
cd /tmp && rm -rf gctest && mkdir gctest && cd gctest && git init -q && git config user.email t@t && git config user.name t
omx wiki add --root . --title "Page One" --category reference --content "first" --confidence medium
omx wiki add --root . --title "Page Two" --category reference --content "second" --confidence medium
git add -A && git commit -qm seed
omx wiki gc --root .
printf -- '---\nkind: wiki-gc\n---\n\n## MERGE\n\n- into: page_one.md\n  from:\n    - page_two.md\n  reason: smoke\n' > prop.md
omx wiki gc-apply --proposal prop.md --root .
omx wiki list --root .
```
Expected: `gc` prints lint+pages; `gc-apply` prints `{"deleted": [], "merged": [{"into": "page_one.md", "from": ["page_two.md"]}]}`; final `list` shows only `page_one.md`, and `omx wiki read --slug page_one.md --root .` contains "Merged from page_two.md".

- [ ] **Step 5: Commit the release**

```bash
cd /root/oh-my-experiments
git add .claude-plugin/plugin.json CHANGELOG.md
git commit -m "release(omx): wiki gc consolidation feature (v0.1.7)"
```

---

## Notes for the executor

- **Push is user-gated.** Do NOT `git push` — commit only. (Prior v0.1.6 commit `4a60e5a` is also unpushed; this builds on it.)
- **Editable install / two pythons:** the `omx` console script runs system python 3.12; the test suite runs under whatever `python -m pytest` resolves in the omx-core dir. Both see the editable package. If a smoke `omx ...` call can't import, run the equivalent via `python -m omx_core.cli ...` from `omx-core/`.
- **The single most important test** is `test_apply_gc_missing_slug_aborts_with_zero_changes` / `test_apply_gc_untracked_aborts_with_zero_changes` — they prove the two-phase "no partial apply" guarantee. If either is weak, the whole safety story is weak.
- **Do not run gc-apply against the live `constrained-albc/.omx`** during implementation — use `tmp_path`/`/tmp/gctest`. The live wiki gets consolidated later, deliberately, as a separate user-approved action.
```
