"""T12: promote-recipe (#15, spec 2.6) — mechanical promotion of a debugging
post into a diagnostic recipe. The OMC 3-question gate is prompt-side; the verb
is a reversible file creation.

The three `count_query_hits` tests that used to live here are gone with the
function. It counted `## [...] query` blocks in the wiki's own query log, and
hq keeps no query log — so the usage signal is a real capability loss (recorded
in the CHANGELOG), not a test to rewrite. `query_count` left the recipe
frontmatter with it.
"""
import json
from pathlib import Path

import pytest
from conftest import hq_stub
from omx_core.omx_paths import OmxError, OmxPaths
from omx_core.wiki import hq_backend
from omx_core.wiki.recipe import promote_recipe

NOW = "2026-07-07T12:00:00"
SLUG = "finding/007"
BODY = "Symptom: z_std collapses.\n\nCheck: run z_sweep per dim."


def _paths(tmp_path):
    return OmxPaths(root=str(tmp_path))


@pytest.fixture
def hq_post(monkeypatch):
    """Serve one post through the hq seam; `topic` is what promote-recipe gates on."""
    import subprocess as _sp

    state = {"topic": "debugging", "present": True}
    monkeypatch.undo()

    def _run(cmd, **kw):
        if not state["present"]:
            payload = {"post": None}
        else:
            payload = {"post": {"id": SLUG, "title": "Encoder z-collapse diagnosis",
                                "fields": {"topic": state["topic"]}, "body": BODY}}
        return _sp.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(hq_backend, "subprocess", hq_stub(_run))
    return state


def test_recipes_dir_path(tmp_path):
    assert _paths(tmp_path).recipes_dir() == tmp_path / ".omx" / "recipes"


def test_promote_writes_recipe_with_frontmatter(tmp_path, hq_post):
    paths = _paths(tmp_path)
    res = promote_recipe(paths, slug=SLUG, now=NOW)
    expected = paths.recipes_dir() / "finding-007.md"
    assert res["recipe"] == str(expected)
    assert Path(res["recipe"]).name.count(".md") == 1
    text = expected.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert f"source_slug: {SLUG}" in text
    assert f"promoted_at: {NOW}" in text
    assert "Symptom: z_std collapses." in text


def test_a_post_id_never_becomes_a_path_separator(tmp_path, hq_post):
    """`finding/007` as a filename would nest the recipe under a per-category
    directory, and a `/` inside a filename component is a traversal seam."""
    res = promote_recipe(_paths(tmp_path), slug=SLUG, now=NOW)
    assert "/finding/" not in res["recipe"]
    assert Path(res["recipe"]).parent == _paths(tmp_path).recipes_dir()


def test_promote_custom_name_and_force(tmp_path, hq_post):
    paths = _paths(tmp_path)
    res = promote_recipe(paths, slug=SLUG, now=NOW, name="z-collapse")
    assert res["recipe"].endswith("z-collapse.md")
    with pytest.raises(OmxError):
        promote_recipe(paths, slug=SLUG, now=NOW, name="z-collapse")
    promote_recipe(paths, slug=SLUG, now=NOW, name="z-collapse", force=True)


def test_promote_rejects_missing_page(tmp_path, hq_post):
    hq_post["present"] = False
    with pytest.raises(OmxError):
        promote_recipe(_paths(tmp_path), slug="nope", now=NOW)


def test_promote_rejects_a_non_debugging_topic(tmp_path, hq_post):
    hq_post["topic"] = "convention"
    with pytest.raises(OmxError) as exc:
        promote_recipe(_paths(tmp_path), slug=SLUG, now=NOW)
    # The message, not just the type: the gate and "post not found" both raise
    # OmxError, and a type-only assertion passes when the wrong one fires.
    assert "debugging" in str(exc.value)


def test_cli_promote_recipe(tmp_path, capsys, hq_post):
    from omx_core import cli
    capsys.readouterr()
    rc = cli.main(["wiki", "promote-recipe", "--slug", SLUG, "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["recipe"].endswith("finding-007.md")
