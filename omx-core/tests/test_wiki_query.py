"""Read-side tests for the wiki views after B4 moved the store to hq.

The six scoring tests that used to live here (title-over-content, tag boost,
confidence/status tie-breaking, near-tie inversion) are gone from this file on
purpose: after B4 omx does not score anything, hq does. Their subject moved to
`skills/harness/tests/test_hq.py` in oh-my-orchestrator, which covers the same
claims against the ranker that now owns them. What stays here is what omx still
decides -- the catalog, the tokenizer, the result shaping, and the limit.
"""
import json

import pytest
from conftest import hq_stub
from omx_core.omx_paths import OmxPaths
from omx_core.wiki import hq_backend, query


def _fake_hq(monkeypatch, *, posts=None, exc=None, rc=0, stdout=None):
    """Stand in for the `hq` subprocess.

    Patches `hq_backend.subprocess`, not `query.subprocess`: after B4 every
    shell-out goes through the one backend module, and a fake aimed at the old
    location would silently let the real `hq` answer -- which is how a test
    starts depending on whether this machine has the tool installed.
    """
    import subprocess as _sp

    monkeypatch.undo()   # drop the autouse stub for this test

    def _run(cmd, **kw):
        if exc is not None:
            raise exc
        payload = stdout if stdout is not None else json.dumps({"posts": posts or []})
        return _sp.CompletedProcess(cmd, rc, stdout=payload, stderr="boom")

    monkeypatch.setattr(hq_backend, "subprocess", hq_stub(_run))
    return query


def _spy_hq(monkeypatch, payload=None):
    """Like `_fake_hq` but hands back the argv it was called with."""
    import subprocess as _sp

    seen = {}
    monkeypatch.undo()

    def _run(cmd, **kw):
        seen["cmd"] = cmd
        return _sp.CompletedProcess(
            cmd, 0, stdout=json.dumps(payload if payload is not None else {"posts": []}),
            stderr="")

    monkeypatch.setattr(hq_backend, "subprocess", hq_stub(_run))
    return seen


def test_enumerate_pages_reads_the_post_store(tmp_path, monkeypatch):
    """The wiki->posts conversion left open leads in posts while `omx wiki list`
    kept reading the (now empty) wiki dir, so the queue-launch gate passed on a
    blind roster. The post store is the only source now."""
    p = OmxPaths(root=tmp_path)
    q = _fake_hq(monkeypatch, posts=[
        {"id": "finding/075", "title": "J2 cable snapped",
         "fields": {"topic": "debugging", "status": "needs-apply-before-retrain"}},
        {"id": "finding/001", "title": "no status", "fields": {"status": "none"}},
    ])
    res = q.enumerate_pages(p)
    assert res["post_store"] == {"ok": True, "count": 1, "total": 2,
                                 "error": None}
    # `total` counts every post, `count` only the actionable ones -- the
    # denominator the queue-launch gate needs to tell "no open gates" from
    # "nobody ever filed one".
    assert [pg["slug"] for pg in res["pages"]] == ["finding/075"]
    post = res["pages"][0]
    assert post["status"] == "needs-apply-before-retrain"   # the blocking status survives
    assert post["category"] == "debugging" and post["blocked_on"] is None


def test_enumerate_pages_reports_an_unreadable_post_store(tmp_path, monkeypatch):
    """An unreadable store is not an empty one -- the whole point of the fix is
    that a zero from an unread source must never read as 'nothing open'."""
    p = OmxPaths(root=tmp_path)
    q = _fake_hq(monkeypatch, exc=FileNotFoundError("hq"))
    res = q.enumerate_pages(p)
    assert res["post_store"]["ok"] is False
    assert "PATH" in res["post_store"]["error"]
    assert res["pages"] == []            # degrades, never fails


def test_enumerate_pages_treats_a_failed_hq_as_unreadable(tmp_path, monkeypatch):
    p = OmxPaths(root=tmp_path)
    q = _fake_hq(monkeypatch, rc=2)
    assert q.enumerate_pages(p)["post_store"]["ok"] is False
    q = _fake_hq(monkeypatch, stdout="not json")
    assert q.enumerate_pages(p)["post_store"]["ok"] is False


def test_enumerate_pages_passes_the_status_filter_through(tmp_path, monkeypatch):
    seen = _spy_hq(monkeypatch)
    query.enumerate_pages(OmxPaths(root=tmp_path), status="needs-experiment")
    assert "--status" in seen["cmd"] and "needs-experiment" in seen["cmd"]


def test_there_is_only_one_tokenizer_and_it_is_hqs():
    """omx's `tokenize` is gone, and its absence is the point.

    It was exported, unused after B4, and it disagreed with the engine that
    actually searches: `자세 제어` gave omx `['자','세','자세','제','어','제어']`
    and hq `['자세','제어']`. A caller trusting the exported one to predict what
    a query would match was reading the wrong rule. Found by a cross-model
    review.
    """
    assert not hasattr(query, "tokenize")
    from omx_core import wiki
    assert "tokenize" not in wiki.__all__ and not hasattr(wiki, "tokenize")


def test_query_empty_store_returns_zero(tmp_path, monkeypatch):
    q = _fake_hq(monkeypatch, posts=[])
    res = q.query_wiki(OmxPaths(root=tmp_path), now="2026-05-31T10:00:00", text="anything")
    assert res == {"n_matches": 0, "n_returned": 0, "matches": [], "corrupt_pages": []}


def test_query_is_not_silently_empty_when_hq_is_missing(tmp_path, monkeypatch):
    """The defect B4 exists to fix, pinned from the other side: a store omx
    cannot read must raise, never return the same shape as a store with nothing
    in it. This repo has lost three tools to reading a zero as an absence."""
    q = _fake_hq(monkeypatch, exc=FileNotFoundError("hq"))
    with pytest.raises(hq_backend.HqUnavailable) as exc:
        q.query_wiki(OmxPaths(root=tmp_path), now="2026-05-31T10:00:00", text="anything")
    assert "PATH" in str(exc.value)


def test_query_match_dict_carries_the_fields_callers_read(tmp_path, monkeypatch):
    q = _fake_hq(monkeypatch, posts=[
        {"id": "finding/007", "title": "Heavy tail",
         "fields": {"topic": "debugging", "confidence": "low",
                    "status": "needs-experiment", "summary": "the tail is heavy"},
         "score": {"field": 8, "body": 3}},
    ])
    m = q.query_wiki(OmxPaths(root=tmp_path), now="2026-05-31T10:00:00",
                     text="heavy")["matches"][0]
    assert m["slug"] == "finding/007" and m["category"] == "debugging"
    assert m["confidence"] == "low" and m["status"] == "needs-experiment"
    # One scalar, and one that AGREES with hq's (field, body) ordering:
    # `field * 10 + body` let (7, 34.96) compose above (10, 0) and invert the
    # list for anyone who re-sorted by it.
    assert m["score"] == 8003
    assert m["snippet"] == "the tail is heavy"


def test_the_scalar_score_never_contradicts_hqs_order(tmp_path, monkeypatch):
    q = _fake_hq(monkeypatch, posts=[
        {"id": "finding/001", "title": "a", "fields": {}, "score": {"field": 10, "body": 0}},
        {"id": "finding/002", "title": "b", "fields": {}, "score": {"field": 7, "body": 34.96}},
    ])
    matches = q.query_wiki(OmxPaths(root=tmp_path), now="2026-05-31T10:00:00",
                           text="x")["matches"]
    assert [m["slug"] for m in matches] == ["finding/001", "finding/002"]
    assert matches[0]["score"] > matches[1]["score"]   # sortable, and the same order


def test_the_absence_sentinel_never_becomes_a_snippet(tmp_path, monkeypatch):
    """`summary: none` is explicit absence, which hq's ranker already reads that
    way. Rendering it produced a snippet reading literally `none`."""
    q = _fake_hq(monkeypatch, posts=[
        {"id": "finding/001", "title": "a", "fields": {"summary": "none"},
         "score": {"field": 1, "body": 0}},
    ])
    m = q.query_wiki(OmxPaths(root=tmp_path), now="2026-05-31T10:00:00",
                     text="x")["matches"][0]
    assert m["snippet"] == ""


def test_query_asks_hq_for_the_metadata_weighting(tmp_path, monkeypatch):
    """omx opted into hq's `--weight-metadata` (user decision, r6). Dropping the
    flag is a silent behaviour change nothing else would catch, since the
    result shape is identical either way."""
    seen = _spy_hq(monkeypatch)
    query.query_wiki(OmxPaths(root=tmp_path), now="2026-05-31T10:00:00", text="x")
    assert "--weight-metadata" in seen["cmd"]


def test_query_category_filters_by_hq_topic(tmp_path, monkeypatch):
    seen = _spy_hq(monkeypatch)
    query.query_wiki(OmxPaths(root=tmp_path), now="2026-05-31T10:00:00", text="x",
                     category="debugging")
    assert "--topic" in seen["cmd"] and "debugging" in seen["cmd"]


def test_query_tags_filter_against_the_posts_keywords(tmp_path, monkeypatch):
    """hq has no keyword-set filter, so this one stays omx-side. It must read
    `keywords:` the way hq writes it -- comma-separated, case-insensitive."""
    q = _fake_hq(monkeypatch, posts=[
        {"id": "finding/001", "title": "a", "fields": {"keywords": "Servo, Gain"},
         "score": {"field": 1, "body": 0}},
        {"id": "finding/002", "title": "b", "fields": {"keywords": "buoyancy"},
         "score": {"field": 1, "body": 0}},
    ])
    res = q.query_wiki(OmxPaths(root=tmp_path), now="2026-05-31T10:00:00",
                       text="x", tags=["servo"])
    assert [m["slug"] for m in res["matches"]] == ["finding/001"]


def test_query_n_matches_is_total_not_truncated(tmp_path, monkeypatch):
    """Skills read n_matches to judge coverage, so it has to be the full matched
    set rather than the slice the limit returned."""
    q = _fake_hq(monkeypatch, posts=[
        {"id": f"finding/{i:03d}", "title": "Heavy tail", "fields": {},
         "score": {"field": 1, "body": 0}} for i in range(5)
    ])
    res = q.query_wiki(OmxPaths(root=tmp_path), now="2026-05-31T10:00:00",
                       text="heavy", limit=2)
    assert res["n_matches"] == 5 and res["n_returned"] == 2
    assert len(res["matches"]) == 2


def test_query_preserves_hqs_order(tmp_path, monkeypatch):
    """Ranking is hq's now. omx must not re-sort -- if it did, the two would
    disagree about one ordering, which is the defect class this round keeps
    finding."""
    q = _fake_hq(monkeypatch, posts=[
        {"id": "finding/003", "title": "third", "fields": {}, "score": {"field": 0, "body": 9}},
        {"id": "finding/001", "title": "first", "fields": {}, "score": {"field": 5, "body": 0}},
    ])
    res = q.query_wiki(OmxPaths(root=tmp_path), now="2026-05-31T10:00:00", text="x")
    assert [m["slug"] for m in res["matches"]] == ["finding/003", "finding/001"]
