"""omx_core.wiki.recipe — promote a debugging wiki page into a reusable
diagnostic recipe (#15, spec 2.6).

The verb is MECHANICAL: it validates the page, computes the usage signal from
the query log, and writes .omx/recipes/<name>.md. The OMC 3-question gate
(not Googleable / workspace-specific / took real effort) is prompt-side with a
human gate — the skills ask the user BEFORE running this."""
from __future__ import annotations

from omx_core.omx_paths import OmxError, OmxPaths, atomic_path
from omx_core.wiki.storage import read_page


def count_query_hits(paths: OmxPaths, slug: str) -> int:
    """Usage signal: the number of `## [...] query` blocks in registry/log.md
    whose `- **Pages:**` list contains `slug` ("queries that RETURNED this
    page" — one defined parse, spec 2.6; storage.append_log writes the format)."""
    log = paths.wiki_log()
    if not log.exists():
        return 0
    count = 0
    in_query_block = False
    for line in log.read_text(encoding="utf-8").splitlines():
        if line.startswith("## ["):
            in_query_block = line.rstrip().endswith("] query")
        elif in_query_block and line.startswith("- **Pages:**"):
            pages = [p.strip() for p in line[len("- **Pages:**"):].split(",")]
            if slug in pages:
                count += 1
            in_query_block = False  # one Pages line per block
    return count


def promote_recipe(paths: OmxPaths, *, slug: str, now: str, name=None,
                   force: bool = False) -> dict:
    """Write .omx/recipes/<name>.md from a debugging page. Loud-fail (OmxError):
    page absent; category != debugging; target exists without force."""
    page = read_page(paths, slug)
    if page is None:
        raise OmxError(f"wiki page not found: {slug!r}")
    if page.category != "debugging":
        raise OmxError(
            f"promote-recipe only promotes category 'debugging' pages; "
            f"{slug!r} is {page.category!r}.")
    recipe_name = name or slug
    target = paths.recipes_dir() / f"{recipe_name}.md"
    if target.exists() and not force:
        raise OmxError(f"recipe already exists: {target} (pass --force to overwrite)")
    hits = count_query_hits(paths, slug)
    body = (
        "---\n"
        f"source_slug: {slug}\n"
        f"promoted_at: {now}\n"
        f"query_count: {hits}\n"
        "---\n\n"
        f"# Recipe: {page.title}\n\n"
        f"{page.content.strip()}\n")
    target.parent.mkdir(parents=True, exist_ok=True)
    with atomic_path(target) as tmp:
        tmp.write_text(body, encoding="utf-8")
    return {"recipe": str(target), "query_count": hits}
