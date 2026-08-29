"""Integration tests: these go through the REAL `hq` binary.

A mock of hq is a second reader of hq's format, and two readers drifting is
the defect this migration removes. Everything the mocks cannot see -- the
append-merge round trip, the no-git supersede asymmetry, the loud failure
when the binary is gone -- has to be checked against the binary itself.
"""

from omx_core import cli
from omx_core.wiki import hq_backend


def _anchor(root):
    (root / ".hq").mkdir()
    (root / ".hq/.anchor").write_text("id: test-anchor\n")


def test_korean_title_subjects_are_nonempty_distinct_and_safe():
    first = hq_backend.title_to_subject("랭킹 재설계")
    second = hq_backend.title_to_subject("자동 캡처")
    assert first and second and first != second
    assert " · " not in first


def test_append_merge_round_trip_on_git_anchor(tmp_path, live_hq):
    _anchor(tmp_path)
    (tmp_path / ".git").mkdir()
    first = hq_backend.write_knowledge(
        tmp_path, now="2026-01-01T00:00:00", title="Same title", content="first body",
        tags=["one"], category="decision", confidence="high")
    second = hq_backend.write_knowledge(
        tmp_path, now="2026-01-01T00:00:01", title="Same title", content="second body",
        tags=["one"], category="decision", confidence="high")
    third = hq_backend.write_knowledge(
        tmp_path, now="2026-01-01T00:00:02", title="Same title", content="second body",
        tags=["one"], category="decision", confidence="high")
    post = hq_backend.read_post(tmp_path, first["slug"])
    assert first["slug"] == second["slug"]
    assert second["action"] == "updated"
    assert third["action"] == "unchanged"
    assert "first body" in post["body"]
    assert "second body" in post["body"]
    assert post["body"].count("## Update (") == 1


def test_no_git_anchor_supersedes_and_lints_one_head(tmp_path, live_hq):
    _anchor(tmp_path)
    first = hq_backend.write_knowledge(
        tmp_path, now="2026-01-01T00:00:00", title="Mutable", content="first",
        tags=[], category="decision", confidence="high")
    second = hq_backend.write_knowledge(
        tmp_path, now="2026-01-01T00:00:01", title="Mutable", content="second",
        tags=[], category="decision", confidence="high")
    assert first["slug"] != second["slug"]
    assert hq_backend.hq_json(tmp_path, "lint")["errors"] == []


def test_cli_query_hq_absence_is_loud_not_zero(tmp_path, capsys, live_hq, monkeypatch):
    monkeypatch.setenv("PATH", "")
    rc = cli.main(["wiki", "query", "--root", str(tmp_path), "anything"])
    captured = capsys.readouterr()
    assert rc != 0
    assert "hq not on PATH" in captured.err
    assert '"n_matches": 0' not in captured.out


def test_lint_quality_floor_is_rejected_by_argparse(tmp_path, capsys):
    rc = cli.main(["wiki", "lint", "--root", str(tmp_path), "--quality-floor", "10"])
    assert rc != 0
    assert "unrecognized arguments" in capsys.readouterr().err


def test_the_absence_sentinel_is_accepted_the_way_hq_accepts_it(tmp_path, live_hq):
    """omx's constant sets mirror hq's and must not disagree about one schema.

    `"none"` is the store's explicit-absence sentinel, and hq's `post --status
    none` is its documented default -- but omx's STATUSES/CONFIDENCES omitted
    it, so the Python API refused a value the store considers normal. Found by
    a cross-model review.
    """
    _anchor(tmp_path)
    (tmp_path / ".git").mkdir()
    res = hq_backend.write_knowledge(
        tmp_path, now="2026-01-01T00:00:00", title="Sentinel", content="body",
        tags=[], category="decision", confidence="none", status="none")
    assert res["action"] == "created"


def test_the_actionable_subset_excludes_the_sentinel():
    """`none` is a valid status and NOT a backlog item; the two sets have to
    stay distinct or `wiki list --status none` becomes a legal, meaningless
    query and the launch gate's roster grows by every status-less post."""
    assert "none" in hq_backend.STATUSES
    assert "none" not in hq_backend.ACTIONABLE_STATUSES
    assert set(hq_backend.BLOCKING_STATUSES) <= set(hq_backend.ACTIONABLE_STATUSES)


def test_an_unknown_status_is_still_refused(tmp_path):
    """Widening the set must not turn it into a pass-through."""
    import pytest
    from omx_core.omx_paths import OmxError
    with pytest.raises(OmxError, match="status"):
        hq_backend.write_knowledge(
            tmp_path, now="2026-01-01T00:00:00", title="x", content="c", tags=[],
            category="decision", confidence="high", status="whatever")
