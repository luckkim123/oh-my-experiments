"""omx_core.wiki.storage — file IO for the wiki (pure, deterministic).

Frontmatter parse/serialize, safe slug paths (traversal blocked via the
omx_paths token validator), and read/write/list pages, auto index
regeneration, an append-only log, and a file mutex. Wall-clock `now` is
injected by callers (CLI), keeping this module unit-testable without a clock.
"""
from __future__ import annotations

import fcntl
import re
import time
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
    if not (v.startswith("[") and v.endswith("]")):
        return [v] if v else []
    inner = v[1:-1].strip()
    if not inner:
        return []
    items, current, in_quote = [], [], False
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == '"' and (i == 0 or inner[i - 1] != "\\"):
            in_quote = not in_quote
            current.append(ch)
        elif ch == "," and not in_quote:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    items.append("".join(current).strip())
    out = []
    for tok in items:
        tok = tok.strip()
        if not tok:
            continue
        if len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"':
            tok = tok[1:-1]
        elif len(tok) >= 2 and tok[0] == "'" and tok[-1] == "'":
            tok = tok[1:-1]
        out.append(_unesc(tok))
    return out


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
    """Title -> '<slug>.md'. Non-ASCII-only titles hash to 'page_<hex>.md'.
    Slugs use underscores (not hyphens) so they pass validate_token's
    [a-z0-9_] constraint and compose correctly with write_page/read_page."""
    base = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:64]
    if not base:
        h = 0
        for ch in title:
            h = ((h << 5) - h + ord(ch)) & 0xFFFFFFFF
        return f"page_{h:08x}.md"
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


def update_index(paths: OmxPaths, *, now: str) -> None:
    """Regenerate registry/index.md from all pages, grouped by category.
    Catalog line = '- [<title>](<slug>) - <first non-empty content line>'.
    Callers MUST hold with_wiki_lock(); this function is not concurrency-safe on its own."""
    pages = []
    for slug in list_pages(paths):
        try:
            page = read_page(paths, slug)
            if page is not None:          # file deleted between scan and read
                pages.append(page)
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
    """Append one operation block to registry/log.md (append-only chronicle).
    Callers MUST hold with_wiki_lock(); this function is not concurrency-safe on its own."""
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
    with open(lock_path, "a", encoding="utf-8") as fh:
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
