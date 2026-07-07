"""T12: promote-recipe (#15, spec 2.6) — mechanical promotion of a debugging
wiki page into a diagnostic recipe, with the query-log usage signal. The OMC
3-question gate is prompt-side; the verb is a reversible file creation."""
import json
from pathlib import Path

import pytest

from omx_core.omx_paths import OmxError, OmxPaths
from omx_core.wiki.ingest import ingest_knowledge
from omx_core.wiki.recipe import count_query_hits, promote_recipe

NOW = "2026-07-07T12:00:00"


def _paths(tmp_path):
    return OmxPaths(root=str(tmp_path))


def _add_debug_page(paths, title="Encoder z-collapse diagnosis"):
    res = ingest_knowledge(
        paths, now=NOW, title=title,
        content="Symptom: z_std collapses.\n\nCheck: run z_sweep per dim.",
        tags=["encoder"], category="debugging", confidence="high",
        sources=["report:x"], quality_score=80, quality_reasons=[])
    return res["slug"]


def test_recipes_dir_path(tmp_path):
    assert _paths(tmp_path).recipes_dir() == tmp_path / ".omx" / "recipes"


def test_count_query_hits_counts_pages_membership(tmp_path):
    paths = _paths(tmp_path)
    slug = _add_debug_page(paths)
    log = paths.wiki_log()
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "# Wiki Log\n\n"
        f"## [{NOW}] query\n- **Pages:** {slug}, other-page\n- **Summary:** q1\n\n"
        f"## [{NOW}] query\n- **Pages:** other-page\n- **Summary:** q2\n\n"
        f"## [{NOW}] add\n- **Pages:** {slug}\n- **Summary:** not a query\n\n"
        f"## [{NOW}] query\n- **Pages:** {slug}\n- **Summary:** q3\n\n",
        encoding="utf-8")
    assert count_query_hits(paths, slug) == 2


def test_count_query_hits_no_log_is_zero(tmp_path):
    paths = _paths(tmp_path)
    assert count_query_hits(paths, "whatever") == 0


def test_count_query_hits_via_real_append_log(tmp_path):
    """Round-trip check: exercise the REAL storage.append_log writer (the
    actual query-log write path) rather than a hand-typed fixture string, so
    the parser is checked against the real format, not the brief's paraphrase."""
    from omx_core.wiki import storage

    paths = _paths(tmp_path)
    slug = _add_debug_page(paths)
    paths.wiki_log().parent.mkdir(parents=True, exist_ok=True)
    storage.append_log(paths, now=NOW, operation="query", pages=[slug, "other-page"],
                       summary="q1")
    storage.append_log(paths, now=NOW, operation="query", pages=["other-page"],
                       summary="q2")
    storage.append_log(paths, now=NOW, operation="add", pages=[slug],
                       summary="not a query")
    storage.append_log(paths, now=NOW, operation="query", pages=[slug],
                       summary="q3")
    assert count_query_hits(paths, slug) == 2


def test_promote_writes_recipe_with_frontmatter(tmp_path):
    paths = _paths(tmp_path)
    slug = _add_debug_page(paths)
    res = promote_recipe(paths, slug=slug, now=NOW)
    expected = paths.recipes_dir() / (slug.removesuffix(".md") + ".md")
    assert res["recipe"] == str(expected) and res["query_count"] == 0
    assert not res["recipe"].endswith(".md.md")
    assert Path(res["recipe"]).name.count(".md") == 1
    recipe = expected
    text = recipe.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert f"source_slug: {slug}" in text
    assert f"promoted_at: {NOW}" in text
    assert "Symptom: z_std collapses." in text


def test_promote_custom_name_and_force(tmp_path):
    paths = _paths(tmp_path)
    slug = _add_debug_page(paths)
    res = promote_recipe(paths, slug=slug, now=NOW, name="z-collapse")
    assert res["recipe"].endswith("z-collapse.md")
    with pytest.raises(OmxError):
        promote_recipe(paths, slug=slug, now=NOW, name="z-collapse")
    promote_recipe(paths, slug=slug, now=NOW, name="z-collapse", force=True)


def test_promote_rejects_missing_page(tmp_path):
    with pytest.raises(OmxError):
        promote_recipe(_paths(tmp_path), slug="nope", now=NOW)


def test_promote_rejects_non_debugging_category(tmp_path):
    paths = _paths(tmp_path)
    res = ingest_knowledge(
        paths, now=NOW, title="A convention", content="x", tags=[],
        category="convention", confidence="high", sources=[],
        quality_score=80, quality_reasons=[])
    with pytest.raises(OmxError):
        promote_recipe(paths, slug=res["slug"], now=NOW)


def test_cli_promote_recipe(tmp_path, capsys):
    from omx_core import cli
    paths = _paths(tmp_path)
    slug = _add_debug_page(paths)
    capsys.readouterr()
    rc = cli.main(["wiki", "promote-recipe", "--slug", slug, "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["query_count"] == 0
    assert out["recipe"].endswith(slug.removesuffix(".md") + ".md")
    assert not out["recipe"].endswith(".md.md")
