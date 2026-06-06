"""Tests for omx_core.wiki.gc — wiki garbage-collect (delete/merge) execution."""
from omx_core.wiki import gc


def test_norm_slug_adds_md_suffix():
    assert gc._norm_slug("foo") == "foo.md"
    assert gc._norm_slug("foo.md") == "foo.md"


def test_gcplan_defaults_are_empty():
    plan = gc.GcPlan()
    assert plan.deletes == []
    assert plan.merges == []


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
