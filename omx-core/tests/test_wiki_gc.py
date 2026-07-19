"""Tests for omx_core.wiki.gc — wiki garbage-collect (delete/merge) execution."""
import subprocess

import pytest
from omx_core.omx_paths import OmxError, OmxPaths
from omx_core.wiki import gc, storage


def test_norm_slug_adds_md_suffix():
    assert gc._norm_slug("foo") == "foo.md"
    assert gc._norm_slug("foo.md") == "foo.md"


def test_gcplan_defaults_are_empty():
    plan = gc.GcPlan()
    assert plan.deletes == []
    assert plan.merges == []


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


def test_apply_gc_rejects_slug_both_deleted_and_merge_source(tmp_path):
    # Cross-block overlap: a slug phase 2 would remove twice (delete + merge
    # source) must abort in phase 1 with ZERO mutations — sequential execution
    # would otherwise loud-fail AFTER the delete already ran (partial apply,
    # contradicting the validate-first guarantee).
    paths = OmxPaths(root=tmp_path)
    x = _seed_page(tmp_path, "Twice Removed")
    s = _seed_page(tmp_path, "Survivor X")
    plan = gc.GcPlan(deletes=[x], merges=[{"into": s, "from": [x]}])
    with pytest.raises(OmxError):
        gc.apply_gc(paths, plan, now="2026-07-16T02:00:00",
                    repo_root=tmp_path, git_check=_always_tracked)
    assert paths.wiki_page(x[:-3]).exists()
    assert paths.wiki_page(s[:-3]).exists()


def test_apply_gc_rejects_chained_merge(tmp_path):
    # Cross-block overlap: merge chain A<-B, B<-C — B is a source in one block
    # and the survivor of another. Sequential execution deletes B in block 1,
    # then block 2 loud-fails on the absent survivor (partial apply). Phase 1
    # must reject the whole plan with zero mutations.
    paths = OmxPaths(root=tmp_path)
    a = _seed_page(tmp_path, "Chain A")
    b = _seed_page(tmp_path, "Chain B")
    c = _seed_page(tmp_path, "Chain C")
    plan = gc.GcPlan(merges=[{"into": a, "from": [b]}, {"into": b, "from": [c]}])
    with pytest.raises(OmxError):
        gc.apply_gc(paths, plan, now="2026-07-16T02:00:00",
                    repo_root=tmp_path, git_check=_always_tracked)
    for slug in (a, b, c):
        assert paths.wiki_page(slug[:-3]).exists()


def test_apply_gc_rejects_duplicate_removal_across_blocks(tmp_path):
    # The same source folded into two different survivors is removed twice.
    paths = OmxPaths(root=tmp_path)
    a = _seed_page(tmp_path, "Surv A")
    b = _seed_page(tmp_path, "Surv B")
    d = _seed_page(tmp_path, "Shared Dup")
    plan = gc.GcPlan(merges=[{"into": a, "from": [d]}, {"into": b, "from": [d]}])
    with pytest.raises(OmxError):
        gc.apply_gc(paths, plan, now="2026-07-16T02:00:00",
                    repo_root=tmp_path, git_check=_always_tracked)
    for slug in (a, b, d):
        assert paths.wiki_page(slug[:-3]).exists()


def test_apply_gc_allows_same_survivor_in_two_blocks(tmp_path):
    # Regression guard for the overlap check: two blocks merging INTO the same
    # survivor are valid sequential merges, not a cross-block hazard.
    paths = OmxPaths(root=tmp_path)
    a = _seed_page(tmp_path, "Multi Keeper", content="keeper body")
    b = _seed_page(tmp_path, "Fold One", content="unique-one")
    c = _seed_page(tmp_path, "Fold Two", content="unique-two")
    plan = gc.GcPlan(merges=[{"into": a, "from": [b]}, {"into": a, "from": [c]}])
    res = gc.apply_gc(paths, plan, now="2026-07-16T02:00:00",
                      repo_root=tmp_path, git_check=_always_tracked)
    assert res["merged"] == [{"into": a, "from": [b]}, {"into": a, "from": [c]}]
    body = storage.read_page(paths, a).content
    assert "unique-one" in body and "unique-two" in body


def test_apply_gc_empty_plan_is_noop(tmp_path):
    paths = OmxPaths(root=tmp_path)
    _seed_page(tmp_path, "Untouched")
    res = gc.apply_gc(paths, gc.GcPlan(), now="2026-06-06T02:00:00",
                      repo_root=tmp_path, git_check=_never_tracked)
    assert res == {"deleted": [], "merged": []}


def test_suggest_delete_candidates_from_orphans_only():
    # Given a lint result, suggest ONLY orphan slugs as delete candidates (not stale).
    lint_res = {
        "issues": [
            {"slug": "lonely.md", "severity": "info", "type": "orphan", "message": "x"},
            {"slug": "old.md", "severity": "info", "type": "stale", "message": "y"},
            {"slug": "bad.md", "severity": "error", "type": "broken-frontmatter", "message": "z"},
        ],
        "stats": {"total_pages": 3, "by_type": {}},
    }
    out = gc.suggest_from_lint(lint_res)
    assert out["delete_candidates"] == ["lonely.md"]   # orphan only; stale/error excluded
    # proposal_skeleton is a ready-to-edit wiki-gc proposal body with the candidate
    assert "kind: wiki-gc" in out["proposal_skeleton"]
    assert "## DELETE" in out["proposal_skeleton"]
    assert "lonely.md" in out["proposal_skeleton"]
    assert "old.md" not in out["proposal_skeleton"]


def test_suggest_from_lint_empty_when_no_orphans():
    lint_res = {"issues": [{"slug": "x.md", "severity": "info", "type": "stale", "message": "m"}],
                "stats": {"total_pages": 1, "by_type": {}}}
    out = gc.suggest_from_lint(lint_res)
    assert out["delete_candidates"] == []


def test_suggest_from_lint_prefills_near_duplicate_merge_pairs():
    # Near-duplicate lint pairs surface under ## MERGE as COMMENTED, NON-directional
    # lines (the detector cannot know the survivor — direction stays human). The
    # lines must be inert to parse_gc_proposal until a human rewrites them into
    # `- into:` / `- <source>` form, so a blind gc-apply of the raw skeleton
    # cannot merge anything.
    lint_res = {
        "issues": [
            {"slug": "fork_a.md", "severity": "info", "type": "near-duplicate",
             "other": "fork_b.md", "message": "slug overlaps 'fork_b.md' at jaccard 0.60"},
        ],
        "stats": {"total_pages": 2, "by_type": {}},
    }
    out = gc.suggest_from_lint(lint_res)
    assert out["merge_candidates"] == [["fork_a.md", "fork_b.md"]]
    skeleton = out["proposal_skeleton"]
    assert "fork_a.md <-> fork_b.md" in skeleton
    plan = gc.parse_gc_proposal(skeleton)
    assert plan.merges == []          # commented pair lines are inert
    assert plan.deletes == []


def test_suggest_from_lint_no_merge_candidates_when_no_near_dups():
    lint_res = {"issues": [{"slug": "x.md", "severity": "info", "type": "stale", "message": "m"}],
                "stats": {"total_pages": 1, "by_type": {}}}
    assert gc.suggest_from_lint(lint_res)["merge_candidates"] == []


def test_suggest_from_lint_exempts_open_lead_slugs():
    # an open-lead page is typically inbound==0 (nothing links to it yet — that's WHY
    # it is a backlog page), so the orphan->delete pipeline must not offer it for deletion.
    lint_res = {
        "issues": [
            {"slug": "backlog.md", "severity": "info", "type": "orphan", "message": "x"},
            {"slug": "backlog.md", "severity": "warning", "type": "open-lead", "message": "y"},
            {"slug": "lonely.md", "severity": "info", "type": "orphan", "message": "z"},
        ],
        "stats": {"total_pages": 2, "by_type": {}},
    }
    out = gc.suggest_from_lint(lint_res)
    assert out["delete_candidates"] == ["lonely.md"]   # backlog.md exempt (open-lead)


def _seed_status_page(tmp_path, title, *, status=None, blocked_on=None, quality_score=None):
    from omx_core.wiki import ingest
    res = ingest.ingest_knowledge(
        OmxPaths(root=tmp_path), now="2026-06-06T00:00:00",
        title=title, content="body", tags=["t"], category="reference",
        confidence="medium", sources=[], status=status, blocked_on=blocked_on,
        quality_score=quality_score)
    return res["slug"]


def test_merge_pages_carries_most_open_status(tmp_path):
    # a duplicate carrying the flag folded into an unflagged survivor must NOT drop the
    # flag (that would silently disarm a HARD gate — the incident, via gc).
    paths = OmxPaths(root=tmp_path)
    into = _seed_status_page(tmp_path, "Keeper")   # no status
    src = _seed_status_page(tmp_path, "Dup", status="needs-apply-before-retrain",
                            blocked_on="measure first")
    gc.merge_pages(paths, into=into, from_slugs=[src], now="2026-06-06T01:00:00")
    page = storage.read_page(paths, into)
    assert page.status == "needs-apply-before-retrain"   # most-open wins
    assert page.blocked_on == "measure first"            # carried from the only source that set it


def test_merge_pages_status_rank_resolved_beats_none(tmp_path):
    paths = OmxPaths(root=tmp_path)
    into = _seed_status_page(tmp_path, "Keeper2")                  # None (rank 0)
    src = _seed_status_page(tmp_path, "Dup2", status="resolved")   # rank 1
    gc.merge_pages(paths, into=into, from_slugs=[src], now="2026-06-06T01:00:00")
    assert storage.read_page(paths, into).status == "resolved"


def test_merge_pages_survivor_blocked_on_wins(tmp_path):
    paths = OmxPaths(root=tmp_path)
    into = _seed_status_page(tmp_path, "Keeper3", status="needs-experiment",
                             blocked_on="survivor reason")
    src = _seed_status_page(tmp_path, "Dup3", status="needs-experiment",
                            blocked_on="source reason")
    gc.merge_pages(paths, into=into, from_slugs=[src], now="2026-06-06T01:00:00")
    assert storage.read_page(paths, into).blocked_on == "survivor reason"   # survivor-first


def test_merge_pages_preserves_survivor_quality(tmp_path):
    # pre-existing bug: merge_pages reconstructed the survivor WITHOUT quality fields,
    # silently dropping them on every merge. The survivor's quality must survive.
    paths = OmxPaths(root=tmp_path)
    into = _seed_status_page(tmp_path, "Quality Keeper", quality_score=85)
    src = _seed_status_page(tmp_path, "Quality Dup")
    gc.merge_pages(paths, into=into, from_slugs=[src], now="2026-06-06T01:00:00")
    assert storage.read_page(paths, into).quality_score == 85
