"""Tests for omx_core.wiki.gc — wiki garbage-collect (delete/merge) execution."""
from omx_core.wiki import gc


def test_norm_slug_adds_md_suffix():
    assert gc._norm_slug("foo") == "foo.md"
    assert gc._norm_slug("foo.md") == "foo.md"


def test_gcplan_defaults_are_empty():
    plan = gc.GcPlan()
    assert plan.deletes == []
    assert plan.merges == []
