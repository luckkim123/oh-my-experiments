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
