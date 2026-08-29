"""Promote a debugging post into a reusable diagnostic recipe."""
from __future__ import annotations

from omx_core.omx_paths import OmxError, OmxPaths, atomic_path
from omx_core.wiki.hq_backend import read_post


def promote_recipe(paths: OmxPaths, *, slug: str, now: str, name=None,
                   force: bool = False) -> dict:
    """Write a recipe from an hq debugging post; hq has no query-log counter."""
    post = read_post(paths.root, slug)
    if post is None:
        raise OmxError(f"wiki page not found: {slug!r}")
    topic = (post.get("fields") or {}).get("topic")
    if topic != "debugging":
        raise OmxError("promote-recipe only promotes topic 'debugging' posts; "
                       f"{slug!r} is {topic!r}.")
    # A post id is `category/NNN`, so the raw slug would put the recipe in a
    # per-category subdirectory (and any `/` in a filename component is a
    # traversal seam waiting for the day ids are not this tidy).
    recipe_name = (name or slug).removesuffix(".md").replace("/", "-")
    target = paths.recipes_dir() / f"{recipe_name}.md"
    if target.exists() and not force:
        raise OmxError(f"recipe already exists: {target} (pass --force to overwrite)")
    body = ("---\n"
            f"source_slug: {slug}\n"
            f"promoted_at: {now}\n"
            "---\n\n"
            f"# Recipe: {post['title']}\n\n"
            f"{str(post.get('body') or '').strip()}\n")
    target.parent.mkdir(parents=True, exist_ok=True)
    with atomic_path(target) as tmp:
        tmp.write_text(body, encoding="utf-8")
    return {"recipe": str(target)}
