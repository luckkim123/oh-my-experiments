# OMX build #8 — Workspace-Specialization Wiki Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote `.omx/registry/findings/` from an empty flat-store seed into an OMC-wiki-style keyword-indexed knowledge layer (frontmatter + auto index/log + tag>title>content keyword search, NO embeddings) so OMX compounds per-workspace.

**Architecture:** A Claude-free `omx_core/wiki/` package (4 modules: types/storage/ingest/query/lint) re-implements OMC's wiki in Python (never imported — pattern only). The core does pure deterministic IO/search/audit with the wall-clock `now` INJECTED by the CLI layer (build #6 pattern); Claude (the skills) decides *what* to record and *which* category. Paths come only from new `omx_paths` getters (path-SSOT). `omx wiki add/query/lint/list` CLI verbs are the seams the 4 skills call.

**Tech Stack:** Python 3.12 stdlib only (`re`, `fcntl`, `pathlib`, `contextlib`, `dataclasses`), reusing existing `omx_core.omx_paths` (`OmxError`, `validate_token`, `atomic_path`) and `omx_core.report.parse_findings`. pytest. No new third-party deps. No embeddings.

**Two governing invariants (verify at FINAL):**
- **INV-1 generality:** the wiki core has ZERO domain knowledge (no isaaclab/uuv/metric names, no absolute paths, no private repo names). Categories are domain-neutral; tags/title/content are runtime inputs.
- **INV-2 compounding:** specialization lives in the DATA (pages under `.omx/registry/`), never the core. append-only merge accrues knowledge without loss; CJK-bigram tokenize makes Korean searchable.

**Reference:** approved design `docs/superpowers/specs/2026-05-31-omx-workspace-wiki-design.md` (decisions W1–W8, §0.1 invariants). OMC source studied (NOT imported): `marketplaces/omc/src/hooks/wiki/{types,storage,ingest,query,lint}.ts`.

**Environment traps (already burned):**
- `python3` NOT `python` (Isaac wrapper). Test cmd: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/ -q`. Baseline before this build: **316 passed, 1 skipped**.
- dist dir `omx-core/` (hyphen) vs import pkg `omx_core/` (underscore). cache ext `.npz`.
- Pyright `reportMissingImports(omx_core.*)` + `"capsys"/"json" is not accessed` = editable/intentional false positives — ignore.
- Korean to user; English in code/comments/markdown; no emojis; no AI-attribution in code/docs (the git trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` is the ONLY allowed exception and is REQUIRED on commits).
- Commit per task (these builds commit directly to local `main`, no feature branch). **Push only on explicit user authorization** (currently 24 commits unpushed; do NOT push).
- Stage explicit paths only (`git add <paths>`), NEVER `git add -A` (concurrent sessions stage the index live).

---

## File Structure

**Create (the wiki package):**
- `omx-core/omx_core/wiki/__init__.py` — public surface: `WikiPage`, `WikiError`, `ingest_knowledge`, `query_wiki`, `lint_wiki`, and the storage read helpers needed by the CLI.
- `omx-core/omx_core/wiki/types.py` — `WikiError`, `WikiPage` dataclass, `CATEGORIES`, `CONFIDENCES`, `WIKI_SCHEMA_VERSION`, `RESERVED_FILES`.
- `omx-core/omx_core/wiki/storage.py` — frontmatter parse/serialize, slug + safe path, read/write/list, `update_index`, `append_log`, `with_wiki_lock`.
- `omx-core/omx_core/wiki/ingest.py` — `ingest_knowledge` (new page or append-merge) + `[[link]]` extraction.
- `omx-core/omx_core/wiki/query.py` — `tokenize` (CJK bigram) + `query_wiki` (scoring + snippet + corrupt-skip).
- `omx-core/omx_core/wiki/lint.py` — `lint_wiki` (orphan/stale/broken-ref/oversized/broken-frontmatter).

**Modify:**
- `omx-core/omx_core/omx_paths.py` — add `wiki_page/wiki_index/wiki_log/wiki_lock/wiki_dir`; REMOVE `finding`/`registry_index`.
- `omx-core/omx_core/__init__.py` — export the wiki public surface.
- `omx-core/omx_core/cli.py` — add `omx wiki add/query/lint/list` subparsers + `_cmd_wiki_*`.
- `skills/exp-init/SKILL.md`, `skills/exp-analyze/SKILL.md`, `skills/exp-design/SKILL.md`, `skills/exp-loop/SKILL.md` — wiki seed/query/add/lint steps.
- `docs/HANDOFF.md`, `docs/design/2026-05-30-omx-experiment-harness-design.md` (mark #8 done), `MEMORY.md`.

**Tests:**
- Create `tests/test_wiki_types.py`, `test_wiki_storage.py`, `test_wiki_ingest.py`, `test_wiki_query.py`, `test_wiki_lint.py`.
- Modify `tests/test_omx_paths.py` (getters), `tests/test_cli.py` (verbs), `tests/test_core_import_safe.py` (exports).

**Each task = one commit. Run the FULL suite after each task; the count only goes up.**

---

### Task 1: omx_paths wiki getters (rename finding → wiki_page, replace registry_index)

**Files:**
- Modify: `omx-core/omx_core/omx_paths.py:190-195` (the `registry/` getter block)
- Test: `omx-core/tests/test_omx_paths.py:210-211,218,260,502-503`

- [ ] **Step 1: Update the failing tests to the new getter names**

In `tests/test_omx_paths.py`, replace the old-getter assertions. Find (around line 210):

```python
    assert p.registry_index() == p.omx_dir / "registry" / "INDEX.md"
    assert p.finding("doraemon_kl") == p.omx_dir / "registry" / "findings" / "doraemon_kl.md"
```

Replace with:

```python
    assert p.wiki_index() == p.omx_dir / "registry" / "index.md"
    assert p.wiki_log() == p.omx_dir / "registry" / "log.md"
    assert p.wiki_lock() == p.omx_dir / "registry" / ".wiki-lock"
    assert p.wiki_dir() == p.omx_dir / "registry" / "findings"
    assert p.wiki_page("doraemon_kl") == p.omx_dir / "registry" / "findings" / "doraemon_kl.md"
```

Find the traversal/bad-slug assertions (around line 218 and 260) that call `p.finding(...)`:

```python
        p.finding("Bad Slug")
```
and
```python
        p.finding(evil)
```
Replace both `p.finding(` with `p.wiki_page(`.

Find the getter-coverage map (around line 502-503):

```python
        "registry_index": lambda: p.registry_index(),
        "finding": lambda: p.finding("slug1"),
```
Replace with:

```python
        "wiki_index": lambda: p.wiki_index(),
        "wiki_log": lambda: p.wiki_log(),
        "wiki_lock": lambda: p.wiki_lock(),
        "wiki_dir": lambda: p.wiki_dir(),
        "wiki_page": lambda: p.wiki_page("slug1"),
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_omx_paths.py -q`
Expected: FAIL — `AttributeError: 'OmxPaths' object has no attribute 'wiki_index'` (and the old `finding`/`registry_index` still exist but are no longer asserted).

- [ ] **Step 3: Replace the getters in omx_paths.py**

In `omx_core/omx_paths.py`, replace the block at lines 190-195:

```python
    # --- registry/ (permanent discovery index) ---
    def registry_index(self) -> Path:
        return self.omx_dir / "registry" / "INDEX.md"

    def finding(self, slug) -> Path:
        return self.omx_dir / "registry" / "findings" / f"{self._check_token(slug, 'slug')}.md"
```

with:

```python
    # --- registry/ wiki (permanent, keyword-indexed knowledge layer; build #8) ---
    def wiki_dir(self) -> Path:
        """registry/findings/ — the dir holding all wiki page .md files."""
        return self.omx_dir / "registry" / "findings"

    def wiki_page(self, slug) -> Path:
        """registry/findings/<slug>.md — one wiki page. slug is a single token
        (validate_token blocks '..'/separators), so traversal is impossible."""
        return self.wiki_dir() / f"{self._check_token(slug, 'slug')}.md"

    def wiki_index(self) -> Path:
        """registry/index.md — auto-regenerated catalog (one line per page)."""
        return self.omx_dir / "registry" / "index.md"

    def wiki_log(self) -> Path:
        """registry/log.md — append-only chronicle of wiki operations."""
        return self.omx_dir / "registry" / "log.md"

    def wiki_lock(self) -> Path:
        """registry/.wiki-lock — file mutex for all wiki writes (fcntl)."""
        return self.omx_dir / "registry" / ".wiki-lock"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_omx_paths.py -q`
Expected: PASS. Then run the full suite — `python3 -m pytest tests/ -q` — and confirm NO other test referenced `finding`/`registry_index` (grep first: `grep -rn "\.finding(\|registry_index(" tests/ omx_core/` must show ZERO hits outside this task's edits).

- [ ] **Step 5: Commit**

```bash
git add omx_core/omx_paths.py tests/test_omx_paths.py
git commit -m "feat(omx-paths): wiki getters (wiki_page/index/log/lock/dir); drop finding/registry_index

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: wiki/types.py — WikiPage dataclass + schema constants

**Files:**
- Create: `omx-core/omx_core/wiki/__init__.py` (empty placeholder for now — package marker)
- Create: `omx-core/omx_core/wiki/types.py`
- Test: `omx-core/tests/test_wiki_types.py`

- [ ] **Step 1: Create the package marker**

Create `omx_core/wiki/__init__.py` with a single line (the real exports come in Task 8):

```python
"""omx_core.wiki — Claude-free keyword-indexed knowledge layer (build #8)."""
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_wiki_types.py`:

```python
from omx_core.wiki.types import (
    WikiError,
    WikiPage,
    CATEGORIES,
    CONFIDENCES,
    WIKI_SCHEMA_VERSION,
    RESERVED_FILES,
)


def test_wiki_error_is_omx_error():
    from omx_core.omx_paths import OmxError
    assert issubclass(WikiError, OmxError)


def test_categories_are_the_eight_domain_neutral_ones():
    assert CATEGORIES == frozenset({
        "architecture", "decision", "pattern", "debugging",
        "environment", "session-log", "reference", "convention",
    })


def test_confidences():
    assert CONFIDENCES == ("high", "medium", "low")


def test_reserved_files():
    assert RESERVED_FILES == frozenset({"index.md", "log.md"})


def test_wikipage_holds_frontmatter_and_content():
    page = WikiPage(
        slug="roll-heavy-tail.md",
        title="Roll heavy-tail",
        tags=["roll", "heavy-tail"],
        created="2026-05-31T10:00:00",
        updated="2026-05-31T10:00:00",
        sources=["20260531-100000-compare"],
        links=["other-slug"],
        category="pattern",
        confidence="high",
        schema_version=1,
        content="some markdown",
    )
    assert page.title == "Roll heavy-tail"
    assert page.category == "pattern"
    assert page.tags == ["roll", "heavy-tail"]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_wiki_types.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.wiki.types'`.

- [ ] **Step 4: Write types.py**

Create `omx_core/wiki/types.py`:

```python
"""omx_core.wiki.types — wiki page schema (data only, no logic).

Re-implements OMC's wiki page shape in Python (pattern, not import). All field
values are runtime inputs — the core carries ZERO domain knowledge (INV-1).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from omx_core.omx_paths import OmxError

#: Bump on a breaking frontmatter change.
WIKI_SCHEMA_VERSION = 1

#: Domain-neutral page categories (INV-1: no experiment-specific names).
CATEGORIES = frozenset({
    "architecture", "decision", "pattern", "debugging",
    "environment", "session-log", "reference", "convention",
})

#: Confidence levels, ordered high -> low (rank index = lower is more confident).
CONFIDENCES = ("high", "medium", "low")

#: Files in the wiki dir that are NOT pages (auto-maintained); never writable as a page.
RESERVED_FILES = frozenset({"index.md", "log.md"})


class WikiError(OmxError):
    """Any wiki loud-fail (bad category/confidence, reserved-file write, lock
    timeout, traversal). Subclass of OmxError so callers catch one base."""


@dataclass(frozen=True)
class WikiPage:
    """One wiki page: frontmatter fields + markdown content + its filename slug."""
    slug: str                      # filename incl. '.md' (e.g. "roll-heavy-tail.md")
    title: str
    tags: list = field(default_factory=list)
    created: str = ""
    updated: str = ""
    sources: list = field(default_factory=list)
    links: list = field(default_factory=list)
    category: str = "reference"
    confidence: str = "medium"
    schema_version: int = WIKI_SCHEMA_VERSION
    content: str = ""
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_wiki_types.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add omx_core/wiki/__init__.py omx_core/wiki/types.py tests/test_wiki_types.py
git commit -m "feat(wiki): page schema types (WikiPage, categories, confidences)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: wiki/storage.py — frontmatter parse/serialize + slug + read/write/list

**Files:**
- Create: `omx-core/omx_core/wiki/storage.py`
- Test: `omx-core/tests/test_wiki_storage.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_wiki_storage.py`:

```python
import pytest

from omx_core.omx_paths import OmxPaths
from omx_core.wiki.types import WikiPage, WikiError
from omx_core.wiki import storage


def _page(slug="alpha.md", title="Alpha", content="hello body"):
    return WikiPage(
        slug=slug, title=title, tags=["t1", "t2"],
        created="2026-05-31T10:00:00", updated="2026-05-31T10:00:00",
        sources=["s1"], links=["beta.md"], category="pattern",
        confidence="high", schema_version=1, content=content,
    )


def test_serialize_then_parse_round_trips(tmp_path):
    page = _page()
    text = storage.serialize_page(page)
    assert text.startswith("---\n")
    parsed = storage.parse_page("alpha.md", text)
    assert parsed.title == "Alpha"
    assert parsed.tags == ["t1", "t2"]
    assert parsed.category == "pattern"
    assert parsed.confidence == "high"
    assert parsed.sources == ["s1"]
    assert parsed.links == ["beta.md"]
    assert "hello body" in parsed.content


def test_parse_page_loud_fails_on_missing_frontmatter():
    with pytest.raises(WikiError):
        storage.parse_page("x.md", "no frontmatter here")


def test_title_to_slug_ascii():
    assert storage.title_to_slug("Roll Heavy-Tail!") == "roll-heavy-tail.md"


def test_title_to_slug_non_ascii_falls_back_to_hash():
    slug = storage.title_to_slug("롤 헤비테일")
    assert slug.startswith("page-") and slug.endswith(".md")


def test_write_then_read_page(tmp_path):
    p = OmxPaths(root=tmp_path)
    storage.write_page(p, _page(), now="2026-05-31T10:00:00")
    got = storage.read_page(p, "alpha.md")
    assert got.title == "Alpha"


def test_write_rejects_reserved_filename(tmp_path):
    p = OmxPaths(root=tmp_path)
    with pytest.raises(WikiError):
        storage.write_page(p, _page(slug="index.md"), now="2026-05-31T10:00:00")


def test_read_missing_page_returns_none(tmp_path):
    p = OmxPaths(root=tmp_path)
    assert storage.read_page(p, "nope.md") is None


def test_list_pages_excludes_reserved(tmp_path):
    p = OmxPaths(root=tmp_path)
    storage.write_page(p, _page(slug="alpha.md"), now="2026-05-31T10:00:00")
    storage.write_page(p, _page(slug="beta.md"), now="2026-05-31T10:00:00")
    assert storage.list_pages(p) == ["alpha.md", "beta.md"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_wiki_storage.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.wiki.storage'`.

- [ ] **Step 3: Write storage.py (parse/serialize/slug/read/write/list — index+log+lock come in Task 4)**

Create `omx_core/wiki/storage.py`:

```python
"""omx_core.wiki.storage — file IO for the wiki (pure, deterministic).

Frontmatter parse/serialize, safe slug paths (traversal blocked via the
omx_paths token validator), read/write/list pages, auto index regeneration,
append-only log, and a file mutex. The wall-clock `now` is INJECTED by callers
(the CLI), so this module is unit-testable without a clock (build #6 pattern).
"""
from __future__ import annotations

import re
from pathlib import Path

from omx_core.omx_paths import OmxPaths, atomic_path
from omx_core.wiki.types import (
    WikiError,
    WikiPage,
    RESERVED_FILES,
    WIKI_SCHEMA_VERSION,
)

_FM_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")


def _unesc(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            out.append({"n": "\n", "r": "\r", '"': '"', "\\": "\\"}.get(nxt, nxt))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _parse_array(value: str) -> list:
    v = value.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_unesc(x.strip().strip('"').strip("'")) for x in inner.split(",") if x.strip()]
    return [v] if v else []


def _parse_yaml(block: str) -> dict:
    out: dict = {}
    for line in block.split("\n"):
        idx = line.find(":")
        if idx == -1:
            continue
        key = line[:idx].strip()
        val = line[idx + 1:].strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = _unesc(val[1:-1])
        if key:
            out[key] = val
    return out


def serialize_page(page: WikiPage) -> str:
    """WikiPage -> markdown string with a '---' YAML frontmatter block."""
    yaml = "\n".join([
        f'title: "{_esc(page.title)}"',
        "tags: [" + ", ".join(f'"{_esc(t)}"' for t in page.tags) + "]",
        f"created: {page.created}",
        f"updated: {page.updated}",
        "sources: [" + ", ".join(f'"{_esc(s)}"' for s in page.sources) + "]",
        "links: [" + ", ".join(f'"{_esc(l)}"' for l in page.links) + "]",
        f"category: {page.category}",
        f"confidence: {page.confidence}",
        f"schemaVersion: {page.schema_version}",
    ])
    return f"---\n{yaml}\n---\n{page.content}"


def parse_page(slug: str, raw: str) -> WikiPage:
    """Markdown string -> WikiPage. Loud-fail (WikiError) on missing frontmatter."""
    normalized = raw.replace("\r\n", "\n")
    m = _FM_RE.match(normalized)
    if not m:
        raise WikiError(f"wiki page {slug!r} has no '---' frontmatter block")
    fm = _parse_yaml(m.group(1))
    try:
        schema_version = int(fm.get("schemaVersion", WIKI_SCHEMA_VERSION))
    except (TypeError, ValueError):
        schema_version = WIKI_SCHEMA_VERSION
    return WikiPage(
        slug=slug,
        title=fm.get("title", ""),
        tags=_parse_array(fm.get("tags", "")),
        created=fm.get("created", ""),
        updated=fm.get("updated", ""),
        sources=_parse_array(fm.get("sources", "")),
        links=_parse_array(fm.get("links", "")),
        category=fm.get("category", "reference"),
        confidence=fm.get("confidence", "medium"),
        schema_version=schema_version,
        content=m.group(2),
    )


def title_to_slug(title: str) -> str:
    """Title -> '<slug>.md'. Non-ASCII-only titles hash to 'page-<hex>.md'
    (mirrors OMC titleToSlug: avoids all CJK titles colliding on '.md')."""
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:64]
    if not base:
        h = 0
        for ch in title:
            h = ((h << 5) - h + ord(ch)) & 0xFFFFFFFF
        return f"page-{h:08x}.md"
    return f"{base}.md"


def read_page(paths: OmxPaths, slug: str) -> WikiPage | None:
    """Read one page. None if absent. Raises WikiError only on a bad slug
    (traversal) — corrupt frontmatter is the CALLER's concern (query reports it)."""
    fp = paths.wiki_page(slug[:-3] if slug.endswith(".md") else slug)
    if not fp.exists():
        return None
    return parse_page(slug, fp.read_text(encoding="utf-8"))


def list_pages(paths: OmxPaths) -> list:
    """Sorted .md filenames under registry/findings/, excluding reserved files."""
    d = paths.wiki_dir()
    if not d.exists():
        return []
    return sorted(
        f.name for f in d.iterdir()
        if f.suffix == ".md" and f.name not in RESERVED_FILES
    )


def write_page(paths: OmxPaths, page: WikiPage, *, now: str) -> None:
    """Atomic-write one page (no index/log/lock yet — Task 4 wraps these)."""
    if page.slug in RESERVED_FILES:
        raise WikiError(f"cannot write a page named {page.slug!r} (reserved)")
    slug_token = page.slug[:-3] if page.slug.endswith(".md") else page.slug
    fp = paths.wiki_page(slug_token)  # validates token -> blocks traversal
    with atomic_path(fp) as tmp:
        Path(tmp).write_text(serialize_page(page), encoding="utf-8")
```

Note: `now` is accepted by `write_page` even though Task-3 body does not stamp with it — Task 4 uses it for index/log. Keeping the signature stable now avoids a churn later.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_wiki_storage.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omx_core/wiki/storage.py tests/test_wiki_storage.py
git commit -m "feat(wiki): storage frontmatter parse/serialize + slug + read/write/list

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: wiki/storage.py — update_index + append_log + with_wiki_lock

**Files:**
- Modify: `omx-core/omx_core/wiki/storage.py` (append functions)
- Test: `omx-core/tests/test_wiki_storage.py` (extend)

- [ ] **Step 1: Write the failing test (append to test_wiki_storage.py)**

Add to `tests/test_wiki_storage.py`:

```python
def test_update_index_groups_by_category(tmp_path):
    p = OmxPaths(root=tmp_path)
    storage.write_page(p, _page(slug="alpha.md", title="Alpha"), now="2026-05-31T10:00:00")
    storage.write_page(p, _page(slug="beta.md", title="Beta"), now="2026-05-31T10:00:00")
    storage.update_index(p, now="2026-05-31T10:00:00")
    index = p.wiki_index().read_text(encoding="utf-8")
    assert "# Wiki Index" in index
    assert "## pattern" in index
    assert "[Alpha](alpha.md)" in index
    assert "[Beta](beta.md)" in index


def test_append_log_is_append_only(tmp_path):
    p = OmxPaths(root=tmp_path)
    storage.append_log(p, now="2026-05-31T10:00:00", operation="add",
                       pages=["alpha.md"], summary="created Alpha")
    storage.append_log(p, now="2026-05-31T10:05:00", operation="query",
                       pages=[], summary="query foo -> 0")
    log = p.wiki_log().read_text(encoding="utf-8")
    assert log.count("## [") == 2
    assert "created Alpha" in log
    assert "query foo -> 0" in log


def test_with_wiki_lock_runs_the_body(tmp_path):
    p = OmxPaths(root=tmp_path)
    out = storage.with_wiki_lock(p, lambda: 42)
    assert out == 42
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_wiki_storage.py -q`
Expected: FAIL — `AttributeError: module 'omx_core.wiki.storage' has no attribute 'update_index'`.

- [ ] **Step 3: Add update_index/append_log/with_wiki_lock to storage.py**

Append to `omx_core/wiki/storage.py` (add `import fcntl`, `import time` to the imports at the top):

```python
def update_index(paths: OmxPaths, *, now: str) -> None:
    """Regenerate registry/index.md from all pages, grouped by category.
    Catalog line = '- [<title>](<slug>) - <first non-empty content line>'."""
    pages = []
    for slug in list_pages(paths):
        try:
            pages.append(read_page(paths, slug))
        except WikiError:
            # corrupt page: skip in the catalog (lint reports it; never crash index)
            continue
    by_cat: dict = {}
    for page in pages:
        by_cat.setdefault(page.category, []).append(page)

    lines = ["# Wiki Index", "", f"> {len(pages)} pages | Last updated: {now}", ""]
    for cat in sorted(by_cat):
        lines.append(f"## {cat}")
        lines.append("")
        for page in by_cat[cat]:
            summary = next((l.strip() for l in page.content.split("\n") if l.strip()), "")
            if len(summary) > 80:
                summary = summary[:77] + "..."
            lines.append(f"- [{page.title}]({page.slug}) - {summary}")
        lines.append("")

    idx = paths.wiki_index()
    with atomic_path(idx) as tmp:
        Path(tmp).write_text("\n".join(lines), encoding="utf-8")


def append_log(paths: OmxPaths, *, now: str, operation: str, pages: list, summary: str) -> None:
    """Append one operation block to registry/log.md (append-only chronicle)."""
    block = (
        f"## [{now}] {operation}\n"
        f"- **Pages:** {', '.join(pages) or 'none'}\n"
        f"- **Summary:** {summary}\n\n"
    )
    log = paths.wiki_log()
    existing = log.read_text(encoding="utf-8") if log.exists() else "# Wiki Log\n\n"
    with atomic_path(log) as tmp:
        Path(tmp).write_text(existing + block, encoding="utf-8")


def with_wiki_lock(paths: OmxPaths, fn, *, timeout_s: float = 5.0, retry_s: float = 0.05):
    """Run `fn` while holding an exclusive fcntl lock on registry/.wiki-lock.
    All wiki WRITES go through this so concurrent sessions never corrupt the wiki.
    Loud-fail (WikiError) if the lock cannot be acquired within timeout_s."""
    lock_path = paths.wiki_lock()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    with open(lock_path, "w", encoding="utf-8") as fh:
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise WikiError(
                        f"wiki lock busy after {timeout_s}s ({lock_path}); another session holds it")
                time.sleep(retry_s)
        try:
            return fn()
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
```

`time.monotonic()` is allowed (it is not a wall clock and is not used for any stamped value — only for the lock timeout). Stamped values (`created`/`updated`/log timestamp) all come from the injected `now`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_wiki_storage.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omx_core/wiki/storage.py tests/test_wiki_storage.py
git commit -m "feat(wiki): auto index regeneration + append-only log + fcntl mutex

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: wiki/ingest.py — ingest_knowledge (new page or append-merge) + [[link]]

**Files:**
- Create: `omx-core/omx_core/wiki/ingest.py`
- Test: `omx-core/tests/test_wiki_ingest.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_wiki_ingest.py`:

```python
import pytest

from omx_core.omx_paths import OmxPaths
from omx_core.wiki.types import WikiError
from omx_core.wiki import ingest, storage


def test_create_new_page(tmp_path):
    p = OmxPaths(root=tmp_path)
    res = ingest.ingest_knowledge(
        p, now="2026-05-31T10:00:00", title="Roll heavy-tail",
        content="roll axis shows heavy tail in hard DR",
        tags=["roll", "heavy-tail"], category="pattern", confidence="high",
        sources=["20260531-100000-compare"],
    )
    assert res["action"] == "created"
    assert res["slug"] == "roll-heavy-tail.md"
    page = storage.read_page(p, "roll-heavy-tail.md")
    assert "heavy tail" in page.content
    assert page.confidence == "high"


def test_revisit_appends_never_replaces(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Roll heavy-tail",
                            content="first observation", tags=["roll"],
                            category="pattern", confidence="medium", sources=["s1"])
    res = ingest.ingest_knowledge(p, now="2026-05-31T11:00:00", title="Roll heavy-tail",
                                  content="second observation", tags=["dr-hard"],
                                  category="pattern", confidence="high", sources=["s2"])
    assert res["action"] == "updated"
    page = storage.read_page(p, "roll-heavy-tail.md")
    assert "first observation" in page.content   # never lost
    assert "second observation" in page.content  # appended
    assert "## Update (2026-05-31T11:00:00)" in page.content
    assert set(page.tags) == {"roll", "dr-hard"}          # union
    assert set(page.sources) == {"s1", "s2"}              # append
    assert page.confidence == "high"                      # max(medium, high)


def test_invalid_category_loud_fails(tmp_path):
    p = OmxPaths(root=tmp_path)
    with pytest.raises(WikiError):
        ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="X",
                                content="c", tags=[], category="not-a-category",
                                confidence="high", sources=[])


def test_invalid_confidence_loud_fails(tmp_path):
    p = OmxPaths(root=tmp_path)
    with pytest.raises(WikiError):
        ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="X",
                                content="c", tags=[], category="pattern",
                                confidence="certain", sources=[])


def test_wiki_links_extracted(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Alpha",
                            content="see [[Roll Heavy-Tail]] for context",
                            tags=[], category="pattern", confidence="low", sources=[])
    page = storage.read_page(p, "alpha.md")
    assert "roll-heavy-tail.md" in page.links
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_wiki_ingest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.wiki.ingest'`.

- [ ] **Step 3: Write ingest.py**

Create `omx_core/wiki/ingest.py`:

```python
"""omx_core.wiki.ingest — write knowledge into the wiki (append-merge, never replace).

ingest_knowledge takes ALREADY-DECIDED fields ({title, content, tags, category,
confidence, sources}) — choosing what to record and how to categorize it is the
SKILL's (Claude's) job (W2). On a slug collision the page is MERGED, never
overwritten: tags union, sources append, confidence max, content appended as a
new timestamped section. This is INV-2: knowledge accrues without loss.
"""
from __future__ import annotations

import re

from omx_core.omx_paths import OmxPaths
from omx_core.wiki.types import (
    WikiError,
    WikiPage,
    CATEGORIES,
    CONFIDENCES,
    WIKI_SCHEMA_VERSION,
)
from omx_core.wiki import storage

_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_CONF_RANK = {"high": 3, "medium": 2, "low": 1}


def _extract_links(content: str) -> list:
    seen = []
    for m in _LINK_RE.findall(content):
        slug = storage.title_to_slug(m.strip())
        if slug not in seen:
            seen.append(slug)
    return seen


def ingest_knowledge(paths: OmxPaths, *, now: str, title: str, content: str,
                     tags: list, category: str, confidence: str,
                     sources: list) -> dict:
    """Create or append-merge a wiki page. Returns {action, slug}."""
    if category not in CATEGORIES:
        raise WikiError(f"category {category!r} not in {sorted(CATEGORIES)}")
    if confidence not in CONFIDENCES:
        raise WikiError(f"confidence {confidence!r} not in {list(CONFIDENCES)}")
    if not title.strip():
        raise WikiError("wiki page title must be non-empty")

    slug = storage.title_to_slug(title)

    def _do() -> dict:
        existing = storage.read_page(paths, slug)
        if existing is None:
            page = WikiPage(
                slug=slug, title=title,
                tags=list(dict.fromkeys(tags)),
                created=now, updated=now,
                sources=list(dict.fromkeys(sources)),
                links=_extract_links(content),
                category=category, confidence=confidence,
                schema_version=WIKI_SCHEMA_VERSION,
                content=f"\n# {title}\n\n{content}\n",
            )
            action = "created"
        else:
            merged_tags = list(dict.fromkeys([*existing.tags, *tags]))
            merged_sources = list(dict.fromkeys([*existing.sources, *sources]))
            merged_links = list(dict.fromkeys([*existing.links, *_extract_links(content)]))
            if _CONF_RANK.get(confidence, 2) >= _CONF_RANK.get(existing.confidence, 2):
                merged_conf = confidence
            else:
                merged_conf = existing.confidence
            appended = existing.content.rstrip() + f"\n\n---\n\n## Update ({now})\n\n{content}\n"
            page = WikiPage(
                slug=slug, title=existing.title,
                tags=merged_tags, created=existing.created, updated=now,
                sources=merged_sources, links=merged_links,
                category=existing.category, confidence=merged_conf,
                schema_version=existing.schema_version, content=appended,
            )
            action = "updated"

        storage.write_page(paths, page, now=now)
        storage.update_index(paths, now=now)
        storage.append_log(paths, now=now, operation="add", pages=[slug],
                           summary=f"{action} {title!r}")
        return {"action": action, "slug": slug}

    return storage.with_wiki_lock(paths, _do)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_wiki_ingest.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omx_core/wiki/ingest.py tests/test_wiki_ingest.py
git commit -m "feat(wiki): ingest_knowledge append-merge (never overwrite) + [[link]] extraction

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: wiki/query.py — tokenize (CJK bigram) + query_wiki + corrupt-skip

**Files:**
- Create: `omx-core/omx_core/wiki/query.py`
- Test: `omx-core/tests/test_wiki_query.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_wiki_query.py`:

```python
from omx_core.omx_paths import OmxPaths
from omx_core.wiki import ingest, query


def test_tokenize_latin_and_digits():
    toks = query.tokenize("Roll Heavy-Tail 42")
    assert "roll" in toks and "heavy" in toks and "tail" in toks and "42" in toks


def test_tokenize_korean_bigrams_and_singletons():
    toks = query.tokenize("롤축")
    assert "롤" in toks and "축" in toks   # singletons
    assert "롤축" in toks                  # bigram


def test_query_empty_wiki_returns_zero(tmp_path):
    p = OmxPaths(root=tmp_path)
    res = query.query_wiki(p, now="2026-05-31T10:00:00", text="anything")
    assert res["n_matches"] == 0
    assert res["matches"] == []
    assert res["corrupt_pages"] == []


def test_query_scores_title_over_content(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Heavy tail",
                            content="unrelated body text", tags=[],
                            category="pattern", confidence="high", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Other",
                            content="this body mentions heavy tail once", tags=[],
                            category="pattern", confidence="high", sources=[])
    res = query.query_wiki(p, now="2026-05-31T10:01:00", text="heavy tail")
    assert res["n_matches"] == 2
    assert res["matches"][0]["title"] == "Heavy tail"   # title match outranks content


def test_query_tag_match_boosts(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="A",
                            content="body", tags=["roll"], category="pattern",
                            confidence="high", sources=[])
    res = query.query_wiki(p, now="2026-05-31T10:01:00", text="roll", tags=["roll"])
    assert res["n_matches"] == 1
    assert res["matches"][0]["slug"] == "a.md"


def test_query_reports_corrupt_page_and_skips_it(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Good",
                            content="heavy tail here", tags=[], category="pattern",
                            confidence="high", sources=[])
    # write a corrupt page directly (no frontmatter)
    p.wiki_dir().mkdir(parents=True, exist_ok=True)
    (p.wiki_dir() / "broken.md").write_text("no frontmatter at all", encoding="utf-8")
    res = query.query_wiki(p, now="2026-05-31T10:01:00", text="heavy")
    assert "broken.md" in res["corrupt_pages"]
    assert any(m["slug"] == "good.md" for m in res["matches"])  # good page still found
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_wiki_query.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.wiki.query'`.

- [ ] **Step 3: Write query.py**

Create `omx_core/wiki/query.py`:

```python
"""omx_core.wiki.query — keyword + tag search (NO vector embeddings — hard constraint).

tokenize handles Latin/digits plus CJK bi-grams (so Korean research notes are
searchable — INV-2). Scoring: tag match > title match > content match (OMC
weights). A page with broken frontmatter is SKIPPED but reported in
`corrupt_pages` (W8: visible-skip, never silent, never whole-fail).
"""
from __future__ import annotations

import re

from omx_core.omx_paths import OmxPaths
from omx_core.wiki.types import WikiError
from omx_core.wiki import storage

_LATIN = re.compile(r"[a-z0-9À-ɏ]+")
_CJK = re.compile(r"[぀-ゟ゠-ヿ一-鿿가-힯]+")


def tokenize(text: str) -> list:
    """Lowercase tokens: Latin/digit words + CJK singletons + CJK bigrams."""
    lower = text.lower()
    tokens = list(_LATIN.findall(lower))
    for seg in _CJK.findall(lower):
        for ch in seg:
            tokens.append(ch)
        for i in range(len(seg) - 1):
            tokens.append(seg[i:i + 2])
    return tokens


def query_wiki(paths: OmxPaths, *, now: str, text: str, tags: list | None = None,
               category: str | None = None, limit: int = 20) -> dict:
    """Search the wiki. Returns {n_matches, matches:[...], corrupt_pages:[...]}."""
    query_lower = text.lower()
    terms = tokenize(text)
    matches = []
    corrupt = []

    for slug in storage.list_pages(paths):
        try:
            page = storage.read_page(paths, slug)
        except WikiError:
            corrupt.append(slug)
            continue
        if page is None:
            continue
        if category is not None and page.category != category:
            continue

        score = 0
        snippet = ""

        if tags:
            overlap = [t for t in tags if any(pt.lower() == t.lower() for pt in page.tags)]
            score += len(overlap) * 3
        for term in terms:
            if any(term in pt.lower() for pt in page.tags):
                score += 2

        title_lower = page.title.lower()
        if query_lower in title_lower:
            score += 5
        else:
            for term in terms:
                if term in title_lower:
                    score += 2

        content_lower = page.content.lower()
        for term in terms:
            idx = content_lower.find(term)
            if idx != -1:
                score += 1
                if not snippet:
                    start = max(0, idx - 40)
                    end = min(len(page.content), idx + len(term) + 80)
                    raw = page.content[start:end].replace("\n", " ").strip()
                    snippet = ("..." if start > 0 else "") + raw + ("..." if end < len(page.content) else "")

        if score > 0:
            if not snippet:
                first = next((l.strip() for l in page.content.split("\n") if l.strip()), "")
                snippet = first[:117] + "..." if len(first) > 120 else first
            matches.append({
                "slug": slug, "title": page.title, "score": score,
                "snippet": snippet, "category": page.category,
                "confidence": page.confidence,
            })

    matches.sort(key=lambda m: m["score"], reverse=True)
    limited = matches[:limit]
    storage.append_log(paths, now=now, operation="query", pages=[m["slug"] for m in limited],
                       summary=f"query {text!r} -> {len(limited)} of {len(matches)}")
    return {"n_matches": len(limited), "matches": limited, "corrupt_pages": corrupt}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_wiki_query.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omx_core/wiki/query.py tests/test_wiki_query.py
git commit -m "feat(wiki): keyword query (CJK bigram, tag>title>content) + corrupt-skip report

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: wiki/lint.py — orphan/stale/broken-ref/oversized/broken-frontmatter audit

**Files:**
- Create: `omx-core/omx_core/wiki/lint.py`
- Test: `omx-core/tests/test_wiki_lint.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_wiki_lint.py`:

```python
from omx_core.omx_paths import OmxPaths
from omx_core.wiki import ingest, lint


def test_lint_clean_wiki_has_no_issues(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="A",
                            content="body", tags=["roll"], category="pattern",
                            confidence="high", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=10240)
    assert res["stats"]["total_pages"] == 1
    types = {i["type"] for i in res["issues"]}
    assert "stale" not in types and "broken-frontmatter" not in types


def test_lint_flags_broken_reference(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="A",
                            content="see [[Ghost Page]] which does not exist",
                            tags=[], category="pattern", confidence="high", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=10240)
    assert any(i["type"] == "broken-ref" for i in res["issues"])


def test_lint_flags_stale(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-01-01T10:00:00", title="Old",
                            content="body", tags=[], category="pattern",
                            confidence="high", sources=[])
    # now is ~150 days later
    res = lint.lint_wiki(p, now="2026-05-31T10:00:00", stale_days=30, max_page_size=10240)
    assert any(i["type"] == "stale" for i in res["issues"])


def test_lint_flags_oversized(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Big",
                            content="x" * 200, tags=[], category="pattern",
                            confidence="high", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=50)
    assert any(i["type"] == "oversized" for i in res["issues"])


def test_lint_flags_broken_frontmatter(tmp_path):
    p = OmxPaths(root=tmp_path)
    p.wiki_dir().mkdir(parents=True, exist_ok=True)
    (p.wiki_dir() / "broken.md").write_text("no frontmatter", encoding="utf-8")
    res = lint.lint_wiki(p, now="2026-05-31T10:00:00", stale_days=30, max_page_size=10240)
    assert any(i["type"] == "broken-frontmatter" and i["slug"] == "broken.md"
               for i in res["issues"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_wiki_lint.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.wiki.lint'`.

- [ ] **Step 3: Write lint.py**

Create `omx_core/wiki/lint.py`:

```python
"""omx_core.wiki.lint — audit the wiki (report-only, NEVER auto-fix; W5).

Detects orphan (no inbound/outbound links), stale (updated older than
stale_days), broken-ref (a [[link]] target slug that does not exist),
oversized (content over max_page_size), and broken-frontmatter (unparseable).
Consumed by `omx wiki lint`, which exp-loop calls at iteration end. The `now`
ISO is injected (no wall clock) so stale detection is deterministic.
"""
from __future__ import annotations

from datetime import datetime

from omx_core.omx_paths import OmxPaths
from omx_core.wiki.types import WikiError
from omx_core.wiki import storage


def _parse_iso(value: str):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def lint_wiki(paths: OmxPaths, *, now: str, stale_days: int = 30,
              max_page_size: int = 10240) -> dict:
    """Audit every page. Returns {issues:[{slug,severity,type,message}], stats:{...}}."""
    now_dt = _parse_iso(now)
    slugs = storage.list_pages(paths)
    pages = {}
    issues = []

    for slug in slugs:
        try:
            page = storage.read_page(paths, slug)
        except WikiError:
            issues.append({"slug": slug, "severity": "error", "type": "broken-frontmatter",
                           "message": "page has no parseable '---' frontmatter"})
            continue
        if page is not None:
            pages[slug] = page

    valid_slugs = set(pages)
    inbound = {s: 0 for s in valid_slugs}
    for slug, page in pages.items():
        for target in page.links:
            if target in valid_slugs:
                inbound[target] = inbound.get(target, 0) + 1
            else:
                issues.append({"slug": slug, "severity": "warning", "type": "broken-ref",
                               "message": f"link target {target!r} does not exist"})

    for slug, page in pages.items():
        if not page.links and inbound.get(slug, 0) == 0:
            issues.append({"slug": slug, "severity": "info", "type": "orphan",
                           "message": "page has no inbound or outbound links"})
        if now_dt is not None:
            updated_dt = _parse_iso(page.updated)
            if updated_dt is not None and (now_dt - updated_dt).days > stale_days:
                issues.append({"slug": slug, "severity": "info", "type": "stale",
                               "message": f"not updated in over {stale_days} days"})
        if len(page.content.encode("utf-8")) > max_page_size:
            issues.append({"slug": slug, "severity": "warning", "type": "oversized",
                           "message": f"content exceeds {max_page_size} bytes"})

    by_type = {}
    for i in issues:
        by_type[i["type"]] = by_type.get(i["type"], 0) + 1
    stats = {"total_pages": len(slugs), "by_type": by_type}
    return {"issues": issues, "stats": stats}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_wiki_lint.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add omx_core/wiki/lint.py tests/test_wiki_lint.py
git commit -m "feat(wiki): lint audit (orphan/stale/broken-ref/oversized/broken-frontmatter), report-only

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: wiki/__init__.py + omx_core export

**Files:**
- Modify: `omx-core/omx_core/wiki/__init__.py`
- Modify: `omx-core/omx_core/__init__.py`
- Test: `omx-core/tests/test_core_import_safe.py` (extend)

- [ ] **Step 1: Write the failing test (extend test_core_import_safe.py)**

Add to `tests/test_core_import_safe.py`:

```python
def test_wiki_public_surface_exported():
    import omx_core
    for name in ("WikiPage", "WikiError", "ingest_knowledge", "query_wiki", "lint_wiki"):
        assert hasattr(omx_core, name), f"omx_core.{name} missing"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_core_import_safe.py::test_wiki_public_surface_exported -q`
Expected: FAIL — `AssertionError: omx_core.WikiPage missing`.

- [ ] **Step 3: Fill wiki/__init__.py then re-export from omx_core/__init__.py**

Replace `omx_core/wiki/__init__.py` with:

```python
"""omx_core.wiki — Claude-free keyword-indexed knowledge layer (build #8).

Re-implements OMC's wiki in Python (pattern, not import). The core does pure
deterministic IO/search/audit; the wall-clock `now` is injected by callers.
"""
from omx_core.wiki.types import WikiError, WikiPage
from omx_core.wiki.ingest import ingest_knowledge
from omx_core.wiki.query import query_wiki, tokenize
from omx_core.wiki.lint import lint_wiki
from omx_core.wiki import storage

__all__ = [
    "WikiError", "WikiPage", "ingest_knowledge", "query_wiki",
    "tokenize", "lint_wiki", "storage",
]
```

In `omx_core/__init__.py`, add to the imports (match the existing `from omx_core.X import (...)` style — find the block of re-exports and append):

```python
from omx_core.wiki import (
    WikiError,
    WikiPage,
    ingest_knowledge,
    query_wiki,
    lint_wiki,
)
```

And add those five names to the module's `__all__` list (append to the existing list).

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_core_import_safe.py -q`
Expected: PASS. Then full suite `python3 -m pytest tests/ -q` — all green.

- [ ] **Step 5: Commit**

```bash
git add omx_core/wiki/__init__.py omx_core/__init__.py tests/test_core_import_safe.py
git commit -m "feat(wiki): export public surface from omx_core

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: cli.py — omx wiki add/query/lint/list verbs

**Files:**
- Modify: `omx-core/omx_core/cli.py` (add `_cmd_wiki_*` + subparsers)
- Test: `omx-core/tests/test_cli.py` (extend)

- [ ] **Step 1: Write the failing test (extend test_cli.py)**

Add to `tests/test_cli.py` (match the existing pattern: build parser, parse args, call `args.func(args)`, capture stdout). Use the existing helper if one exists; otherwise:

```python
import json
from omx_core.cli import build_parser
from omx_core.omx_paths import OmxPaths
from omx_core.wiki import ingest


def _run(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def test_wiki_add_write_mode_creates_page(tmp_path, capsys):
    rc = _run(["wiki", "add", "--root", str(tmp_path), "--title", "Roll heavy-tail",
               "--category", "pattern", "--tags", "roll,heavy-tail",
               "--confidence", "high", "--content", "roll axis heavy tail"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "created"
    assert out["slug"] == "roll-heavy-tail.md"


def test_wiki_add_from_report_extract_only(tmp_path, capsys):
    report = tmp_path / "report.md"
    report.write_text(
        "[FINDING] roll regressed\n[EVIDENCE: summary.json hard/roll]\n[CONFIDENCE: HIGH]\n",
        encoding="utf-8",
    )
    rc = _run(["wiki", "add", "--root", str(tmp_path), "--from-report", str(report)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["candidates"][0]["claim"] == "roll regressed"
    # extract-only wrote nothing:
    assert OmxPaths(root=tmp_path).wiki_dir().exists() is False


def test_wiki_query_returns_json(tmp_path, capsys):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Heavy tail",
                            content="body", tags=[], category="pattern",
                            confidence="high", sources=[])
    rc = _run(["wiki", "query", "--root", str(tmp_path), "heavy tail"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_matches"] == 1


def test_wiki_lint_returns_json(tmp_path, capsys):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="A",
                            content="body", tags=["roll"], category="pattern",
                            confidence="high", sources=[])
    rc = _run(["wiki", "lint", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "issues" in out and "stats" in out


def test_wiki_add_bad_category_loud_fails(tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        _run(["wiki", "add", "--root", str(tmp_path), "--title", "X",
              "--category", "bogus", "--tags", "", "--confidence", "high",
              "--content", "c"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_cli.py -k wiki -q`
Expected: FAIL — `argument cmd: invalid choice: 'wiki'`.

- [ ] **Step 3: Add the wiki commands to cli.py**

In `omx_core/cli.py`, add these imports near the existing `from omx_core...` imports:

```python
from datetime import datetime, timezone
from omx_core.wiki import ingest as _wiki_ingest, query as _wiki_query, lint as _wiki_lint
from omx_core.report import parse_findings
```
(If `datetime, timezone` is already imported from build #6, do not duplicate it.)

Add the command functions (place them near the other `_cmd_*` functions, before `build_parser`):

```python
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cmd_wiki_add(args) -> int:
    paths = OmxPaths(root=args.root)
    if args.from_report is not None:
        report = Path(args.from_report)
        if not report.exists():
            raise SystemExit(f"report not found: {report}")
        try:
            findings = parse_findings(report.read_text(encoding="utf-8"))
        except OmxError as e:
            raise SystemExit(str(e))
        print(json.dumps({"candidates": [
            {"claim": f.claim, "evidence": f.evidence, "confidence": f.confidence}
            for f in findings
        ]}))
        return 0
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    content = args.content
    if content == "-":
        content = sys.stdin.read()
    try:
        res = _wiki_ingest.ingest_knowledge(
            paths, now=_now_iso(), title=args.title, content=content,
            tags=tags, category=args.category, confidence=args.confidence,
            sources=[s.strip() for s in (args.sources or "").split(",") if s.strip()])
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(res))
    return 0


def _cmd_wiki_query(args) -> int:
    paths = OmxPaths(root=args.root)
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()] or None
    try:
        res = _wiki_query.query_wiki(
            paths, now=_now_iso(), text=args.text, tags=tags,
            category=args.category, limit=args.limit)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(res))
    return 0


def _cmd_wiki_lint(args) -> int:
    paths = OmxPaths(root=args.root)
    try:
        res = _wiki_lint.lint_wiki(
            paths, now=_now_iso(), stale_days=args.stale_days,
            max_page_size=args.max_page_size)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(res))
    return 0


def _cmd_wiki_list(args) -> int:
    paths = OmxPaths(root=args.root)
    from omx_core.wiki import storage as _wiki_storage
    out = {"pages": [], "corrupt_pages": []}
    for slug in _wiki_storage.list_pages(paths):
        try:
            page = _wiki_storage.read_page(paths, slug)
        except OmxError:
            out["corrupt_pages"].append(slug)
            continue
        if page is not None:
            out["pages"].append({"slug": slug, "title": page.title, "category": page.category})
    print(json.dumps(out))
    return 0
```

Ensure `import sys` and `from pathlib import Path` and `import json` are present at the top (they are used by sibling commands — verify, do not duplicate).

In `build_parser()`, after the last existing subparser and before `return p`, add:

```python
    pw = sub.add_parser("wiki", help="workspace knowledge wiki (keyword-indexed, no embeddings)")
    wsub = pw.add_subparsers(dest="wiki_cmd", required=True)

    pwa = wsub.add_parser("add", help="add/merge a page, OR --from-report to extract candidates")
    pwa.add_argument("--root", required=True)
    pwa.add_argument("--title", default=None)
    pwa.add_argument("--category", default=None)
    pwa.add_argument("--tags", default=None, help="comma-separated")
    pwa.add_argument("--confidence", default=None, choices=["high", "medium", "low"])
    pwa.add_argument("--content", default=None, help="content text, or '-' for stdin")
    pwa.add_argument("--sources", default=None, help="comma-separated source ids")
    pwa.add_argument("--from-report", default=None, dest="from_report",
                     help="extract-only: print [FINDING] candidates from a report.md, write nothing")
    pwa.set_defaults(func=_cmd_wiki_add)

    pwq = wsub.add_parser("query", help="keyword + tag search (tag>title>content, CJK-aware)")
    pwq.add_argument("--root", required=True)
    pwq.add_argument("text", help="query text")
    pwq.add_argument("--tags", default=None, help="comma-separated tag filter")
    pwq.add_argument("--category", default=None)
    pwq.add_argument("--limit", type=int, default=20)
    pwq.set_defaults(func=_cmd_wiki_query)

    pwl = wsub.add_parser("lint", help="audit pages (orphan/stale/broken-ref/oversized), report-only")
    pwl.add_argument("--root", required=True)
    pwl.add_argument("--stale-days", type=int, default=30, dest="stale_days")
    pwl.add_argument("--max-page-size", type=int, default=10240, dest="max_page_size")
    pwl.set_defaults(func=_cmd_wiki_lint)

    pwls = wsub.add_parser("list", help="catalog of pages (slug/title/category)")
    pwls.add_argument("--root", required=True)
    pwls.set_defaults(func=_cmd_wiki_list)
```

Add a write-mode guard inside `_cmd_wiki_add`: when NOT `--from-report`, `--title`/`--category`/`--content` are required. argparse cannot express "required unless --from-report", so enforce in code at the top of the write branch:

```python
    # (inside _cmd_wiki_add, in the write branch, right before building tags)
    for need in ("title", "category", "content"):
        if getattr(args, need) is None:
            raise SystemExit(f"--{need} is required in write mode (omit only with --from-report)")
    if args.confidence is None:
        raise SystemExit("--confidence is required in write mode")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_cli.py -k wiki -q` then the full suite `python3 -m pytest tests/ -q`.
Expected: PASS, full suite green.

- [ ] **Step 5: Commit**

```bash
git add omx_core/cli.py tests/test_cli.py
git commit -m "feat(cli): omx wiki add/query/lint/list verbs (now injected, --from-report extract-only)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: skill integration — exp-init seed / exp-analyze query+add / exp-design query / exp-loop lint

**Files:**
- Modify: `skills/exp-init/SKILL.md` (seed step)
- Modify: `skills/exp-analyze/SKILL.md` (query before, add after)
- Modify: `skills/exp-design/SKILL.md` (query before diagnosis)
- Modify: `skills/exp-loop/SKILL.md` (lint at iteration end)

This task has no Python tests (SKILL.md is Claude-orchestration prose). Verification = each edit is internally consistent and uses ONLY the `omx wiki` verbs (never a hand-written path). Review checks the wording against the design §2 flow.

- [ ] **Step 1: exp-init — add a seed step after the "Present the profile" section**

In `skills/exp-init/SKILL.md`, after the profile is bootstrapped (after the `omx init` success block, before "## Re-running exp-init"), add:

```markdown
## Seed the workspace wiki (one page from the interview)

After `omx init` succeeds, seed ONE wiki page capturing the conventions you just
elicited — this starts the workspace specialization (the more OMX runs, the more
this wiki knows about THIS workspace). Use ONLY what the interview already gave
you; do NOT ask new questions or scan directories.

```bash
omx wiki add --root "<anchor>" --title "<profile-name> experiment conventions" \
    --category convention --confidence high \
    --tags "<profile-name>,conventions,setup" \
    --content "Objective: <the Goal quantity + direction>.
Metric vocabulary: <the closed metric list>.
keep_policy: <pass_only|score_improvement>. output_root: <the chosen root>.
Launch: <one line on the training command + GPU gate, from launch.sh>."
```

This is the only wiki write exp-init makes. It records workspace conventions, not
findings (those come from exp-analyze). If `omx wiki add` loud-fails, surface the
message and continue — the profile is already written; the seed is best-effort.
```

- [ ] **Step 2: exp-analyze — add query-before and add-after steps**

In `skills/exp-analyze/SKILL.md`, after the "Preconditions" section, add a query step:

```markdown
## Ground in prior workspace knowledge (query the wiki first)

Before analyzing, pull any accumulated knowledge about this run's topic so you do
not re-derive what the workspace already learned:

```bash
omx wiki query --root <root> "<the run's main metric or symptom, e.g. 'roll heavy-tail'>"
```

Read the returned `matches` (snippets + confidence) as CONTEXT, not as findings to
copy. If `corrupt_pages` is non-empty, mention it (lint will flag them). An empty
result is normal for a fresh workspace.
```

And after the "When done" section's report-writing, add an append step:

```markdown
## Record reusable findings into the wiki (after the report is written)

The report.md is this analysis's full deliverable. The wiki holds the SUBSET worth
reusing across future runs. Select only durable, reusable findings (not run-specific
noise) and record each as a page. To not miss candidates, let the core extract them:

```bash
omx wiki add --root <root> --from-report "<output_root>/<run_id>/analysis/<analysis_id>/report.md"
```

This prints `{"candidates": [...]}` and writes NOTHING. Choose the reusable ones,
then write each chosen page (you decide title/category/tags — the core does not):

```bash
omx wiki add --root <root> --title "<short reusable title>" \
    --category <pattern|debugging|decision|reference> --confidence <high|medium|low> \
    --tags "<axis>,<symptom>" --sources "<analysis_id>" \
    --content "<the finding, with its evidence>"
```

Record findings sparingly — a wiki full of every run's noise stops being useful.
Skip this entirely if nothing in the report is reusable beyond this run.
```

- [ ] **Step 3: exp-design — add a query-before-diagnosis step**

In `skills/exp-design/SKILL.md`, after "Step 1 — read the structured findings", add:

```markdown
## Step 1b — query the wiki for prior diagnoses of this symptom

Before the 3-lane diagnosis, check whether the workspace already diagnosed this
symptom (avoids re-deriving a known cause / re-proposing a tried probe):

```bash
omx wiki query --root <root> "<the symptom you are diagnosing>" --category decision
omx wiki query --root <root> "<the symptom you are diagnosing>" --category pattern
```

Treat hits as PRIOR EVIDENCE feeding the lanes (a past confirmed cause is strong
evidence FOR that lane). If a prior probe was already tried, design a DIFFERENT
discriminating probe. An empty result just means this is new ground.
```

- [ ] **Step 4: exp-loop — add a lint step at iteration end**

In `skills/exp-loop/SKILL.md`, in "### 6. Loop or stop", add before the loop-or-stop decision:

```markdown
### 5b. Audit the wiki (report-only, never auto-fix)

At the end of each iteration, audit the accumulated wiki so stale/orphaned/broken
knowledge surfaces (it is review-gated — you report, the human decides):

```bash
omx wiki lint --root <root>
```

Report any `stale` / `broken-ref` / `broken-frontmatter` issues to the user in your
summary. Do NOT auto-edit or delete any page (minimum-change / review-gated rule).
```

Also add to "## Hard constraints (never violate)":

```markdown
- NEVER auto-fix, edit, or delete a wiki page from a lint result. lint is
  report-only; the human decides any change (review-gated).
```

- [ ] **Step 5: Verify internal consistency (no Python test)**

Re-read each edited SKILL.md section. Confirm: every wiki interaction uses an
`omx wiki` verb (no hand-written `.omx/registry/` path); exp-init writes exactly one
page; exp-analyze queries before + adds after; exp-design queries before diagnosing;
exp-loop lints (report-only) at iteration end. The Korean-to-user / English-in-markdown
rule holds (these are English markdown skill bodies).

- [ ] **Step 6: Commit**

```bash
git add skills/exp-init/SKILL.md skills/exp-analyze/SKILL.md skills/exp-design/SKILL.md skills/exp-loop/SKILL.md
git commit -m "feat(skills): wire wiki into the 4 skills (init seed / analyze query+add / design query / loop lint)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: docs + design close-out + MEMORY (no plugin.json change — wiki adds no skill)

**Files:**
- Modify: `docs/design/2026-05-30-omx-experiment-harness-design.md` (mark #8 done)
- Modify: `docs/HANDOFF.md`
- Modify: `/root/.claude/projects/-workspace/memory/MEMORY.md` + new memory file

- [ ] **Step 1: Mark build #8 done in the design DAG**

In `docs/design/2026-05-30-omx-experiment-harness-design.md`, in §8 the `8.` bullet, prepend `**DONE 2026-05-31** — ` to the description (leave the rest as the historical record).

- [ ] **Step 2: Verify plugin.json is unchanged (wiki adds NO skill)**

Run: `grep -c "skills/" /workspace/oh-my-experiments/.claude-plugin/plugin.json` — confirm the `skills` array is still the 4 entries (exp-init/analyze/design/loop). The wiki is core + skill-integration, so NO new skill directory and NO plugin.json edit. If it somehow changed, revert that change.

- [ ] **Step 3: Update HANDOFF.md**

In `docs/HANDOFF.md`, add a `#8 DONE` bullet near the other build bullets:

```markdown
- **#8 workspace-wiki — DONE + on local main (unpushed)** (2026-05-31). Core
  `omx_core/wiki/{types,storage,ingest,query,lint}.py` (OMC wiki re-implemented in
  Python, Claude-free, time-injected) + `omx wiki add/query/lint/list` verbs +
  `omx_paths` wiki getters (finding/registry_index removed) + the 4 skills wired
  (exp-init seed / exp-analyze query+add via --from-report / exp-design query /
  exp-loop lint report-only). NO new skill (plugin.json stays 4). INV-1 generality +
  INV-2 compounding held. Spec `docs/superpowers/specs/2026-05-31-omx-workspace-wiki-design.md`,
  plan `docs/superpowers/plans/2026-05-31-omx-workspace-wiki.md`. NEXT = #7 finalize
  (deploy; claudebase pull-first).
```

- [ ] **Step 4: Update MEMORY**

Create `/root/.claude/projects/-workspace/memory/project_omx_build8_workspace_wiki_2026_05_31.md` (frontmatter: type project) summarizing #8 (what was built, the two invariants, finding/registry_index removed, NO plugin.json change, NEXT=#7). Add one pointer line to `MEMORY.md` under the OMX Harness section.

- [ ] **Step 5: Commit (omx repo docs only — memory is outside the repo, committed implicitly by the memory system)**

```bash
git add docs/design/2026-05-30-omx-experiment-harness-design.md docs/HANDOFF.md
git commit -m "docs(omx): close out build #8 workspace-wiki (design DAG + handoff)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### FINAL: opus cross-cutting review

After all 11 tasks, dispatch one opus reviewer over the whole build #8 diff. Review lenses:

1. **Boundary integrity** — is the core 100% Claude-free and deterministic? Is every wall-clock value injected via `now` (no `datetime.now()`/`Math.random` inside core functions; `time.monotonic` only for the lock timeout)? Do the skills hold all the judgment (what to record, which category)?
2. **INV-1 generality** — grep the wiki core for any domain term (isaaclab, uuv, metric names, absolute paths, private repo names). There must be ZERO. Categories domain-neutral. Shipped content placeholder-only.
3. **INV-2 compounding** — does append-merge never overwrite (revisit appends a timestamped section)? Does CJK tokenize make Korean searchable? Does the 4-skill flow actually accumulate (init seeds, analyze/design append+query, loop lints)?
4. **loud-fail discipline** — bad category/confidence/title raise WikiError; lock timeout raises; corrupt page is visible-skip (in `corrupt_pages`) never silent; empty query is NOT a failure.
5. **path-SSOT** — every wiki path comes from an `omx_paths` getter; no string-concatenated `.omx/registry/` anywhere; `finding`/`registry_index` fully removed (zero dangling refs).
6. **append-only / atomicity** — writes go through `atomic_path` inside `with_wiki_lock`; index regenerates after each write; log is append-only.
7. **repo discipline** — one commit per task, git trailer present, no emojis, no AI-attribution in code/docs, tests count only went up (final ≥ 316 + new), no push.

Then `superpowers:finishing-a-development-branch` (these builds finish on local `main`; push only on explicit user authorization).

---

## Self-Review (run by the plan author — done)

**1. Spec coverage:** W1 Full parity → T2-T7 (all 4 modules + lint). W2 boundary → T5 (ingest takes decided fields) + T9 (CLI injects `now`) + T10 (skills judge). W3 registry redesign → T1 getters. W4 add + --from-report → T9. W5 lint + exp-loop → T7 + T10 step 4. W6 seed interview-only → T10 step 1. W7 approach A 4 modules → T2-T7 file structure. W8 corrupt-skip → T6 (query) + T7 (lint broken-frontmatter). INV-1/INV-2 → FINAL lenses 2-3. All covered.

**2. Placeholder scan:** No TBD/TODO/"handle edge cases". Every code step shows complete code. `<root>`/`<run_id>`/`<output_root>` in SKILL.md snippets are runtime placeholders (intentional, mirror the existing skills). T10 has no Python test by design (prose skill bodies) — verification is explicit consistency checks, not a hand-wave.

**3. Type consistency:** `WikiPage` fields (slug/title/tags/created/updated/sources/links/category/confidence/schema_version/content) consistent T2→T3→T5. `ingest_knowledge(paths, *, now, title, content, tags, category, confidence, sources) -> {action, slug}` consistent T5↔T9. `query_wiki(paths, *, now, text, tags, category, limit) -> {n_matches, matches, corrupt_pages}` consistent T6↔T9. `lint_wiki(paths, *, now, stale_days, max_page_size) -> {issues, stats}` consistent T7↔T9. Getter names `wiki_page/wiki_index/wiki_log/wiki_lock/wiki_dir` consistent T1→all. `storage.write_page(paths, page, *, now)` / `read_page(paths, slug)` / `list_pages(paths)` / `update_index(paths, *, now)` / `append_log(paths, *, now, operation, pages, summary)` / `with_wiki_lock(paths, fn)` consistent T3/T4→T5/T6/T7.

No gaps found.
