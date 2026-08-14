import pytest
from omx_core.omx_paths import OmxPaths
from omx_core.wiki import ingest, storage
from omx_core.wiki.types import WikiError


def test_create_new_page(tmp_path):
    p = OmxPaths(root=tmp_path)
    res = ingest.ingest_knowledge(
        p, now="2026-05-31T10:00:00", title="Roll heavy-tail",
        content="roll axis shows heavy tail in hard DR",
        tags=["roll", "heavy-tail"], category="pattern", confidence="high",
        sources=["20260531-100000-compare"],
    )
    assert res["action"] == "created"
    assert res["slug"] == "roll_heavy_tail.md"
    page = storage.read_page(p, "roll_heavy_tail.md")
    assert "heavy tail" in page.content
    assert page.confidence == "high"


def test_revisit_appends_never_replaces(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Roll heavy-tail",
                            content="first observation", tags=["roll"],
                            category="pattern", confidence="medium", sources=["s1"])
    res = ingest.ingest_knowledge(p, now="2026-05-31T11:00:00", title="Roll heavy-tail",
                                  content="second observation", tags=["dr-hard"],
                                  category="pattern", confidence="high", sources=["s2"])
    assert res["action"] == "updated"
    page = storage.read_page(p, "roll_heavy_tail.md")
    assert "first observation" in page.content   # never lost
    assert "second observation" in page.content  # appended
    assert "## Update (2026-05-31T11:00:00)" in page.content
    assert set(page.tags) == {"roll", "dr-hard"}          # union
    assert set(page.sources) == {"s1", "s2"}              # append
    assert page.confidence == "high"                      # max(medium, high)


def test_invalid_category_loud_fails(tmp_path):
    p = OmxPaths(root=tmp_path)
    with pytest.raises(WikiError):
        ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="X",
                                content="c", tags=[], category="not-a-category",
                                confidence="high", sources=[])


def test_invalid_confidence_loud_fails(tmp_path):
    p = OmxPaths(root=tmp_path)
    with pytest.raises(WikiError):
        ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="X",
                                content="c", tags=[], category="pattern",
                                confidence="certain", sources=[])


def test_empty_title_loud_fails(tmp_path):
    p = OmxPaths(root=tmp_path)
    with pytest.raises(WikiError):
        ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="   ",
                                content="c", tags=[], category="pattern",
                                confidence="high", sources=[])


def test_wiki_links_extracted(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Alpha",
                            content="see [[Roll Heavy-Tail]] for context",
                            tags=[], category="pattern", confidence="low", sources=[])
    page = storage.read_page(p, "alpha.md")
    assert "roll_heavy_tail.md" in page.links


def test_aware_now_loud_fails(tmp_path):
    p = OmxPaths(root=tmp_path)
    with pytest.raises(WikiError):
        ingest.ingest_knowledge(p, now="2026-05-31T10:00:00+00:00", title="X",
                                content="c", tags=[], category="pattern",
                                confidence="high", sources=[])


def test_create_with_status_and_blocked_on(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="TAM row rewrite",
                            content="reorder ESC channels to match firmware",
                            tags=["tam"], category="decision", confidence="high",
                            sources=["meas-20260705"],
                            status="needs-apply-before-retrain",
                            blocked_on="bench-measure T200 curve")
    page = storage.read_page(p, "tam_row_rewrite.md")
    assert page.status == "needs-apply-before-retrain"
    assert page.blocked_on == "bench-measure T200 curve"


def test_merge_explicit_status_wins(tmp_path):
    # resolving a lead: same title, --status resolved flips the flag AND appends the note.
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Command-box eval",
                            content="extend eval to full box", tags=["eval"],
                            category="reference", confidence="medium", sources=[],
                            status="needs-experiment")
    ingest.ingest_knowledge(p, now="2026-05-31T11:00:00", title="Command-box eval",
                            content="applied in abc123", tags=[], category="reference",
                            confidence="medium", sources=[], status="resolved")
    page = storage.read_page(p, "command_box_eval.md")
    assert page.status == "resolved"
    assert "extend eval to full box" in page.content   # INV-2: nothing lost


def test_merge_none_status_keeps_existing(tmp_path):
    # a capture session-stub re-adds with no status -> must NOT clobber the flag.
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="TAM row rewrite",
                            content="hard gate", tags=[], category="decision",
                            confidence="high", sources=[],
                            status="needs-apply-before-retrain",
                            blocked_on="measure first")
    ingest.ingest_knowledge(p, now="2026-05-31T11:00:00", title="TAM row rewrite",
                            content="unrelated session note", tags=[], category="decision",
                            confidence="high", sources=[])   # no status/blocked_on
    page = storage.read_page(p, "tam_row_rewrite.md")
    assert page.status == "needs-apply-before-retrain"   # kept
    assert page.blocked_on == "measure first"            # kept


def test_invalid_status_loud_fails(tmp_path):
    p = OmxPaths(root=tmp_path)
    with pytest.raises(WikiError):
        ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="X",
                                content="c", tags=[], category="pattern",
                                confidence="high", sources=[], status="needs-typo")


def test_identical_content_does_not_append_a_second_time(tmp_path):
    """A re-capture of the same finding must be a no-op, not a duplicate block.

    capture_flush keyed its dedupe on the raw path string, so one report reached
    ingest twice (relative and absolute spelling) and produced byte-identical
    Update blocks. Measured on one workspace: 141 of 550 pages, ~114 KB.
    """
    p = OmxPaths(root=tmp_path)
    body = "roll ss_error 0.31 -> 0.76 from soft to hard (summary.json hard/roll)"
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Roll heavy-tail",
                            content=body, tags=["roll"], category="pattern",
                            confidence="high", sources=["rel/report.md"])
    res = ingest.ingest_knowledge(p, now="2026-05-31T11:00:00", title="Roll heavy-tail",
                                  content=body, tags=["dr-hard"], category="pattern",
                                  confidence="high", sources=["/abs/report.md"])

    page = storage.read_page(p, "roll_heavy_tail.md")
    assert res["action"] == "unchanged"
    assert page.content.count(body) == 1              # not appended twice
    assert "## Update (2026-05-31T11:00:00)" not in page.content
    # metadata still accrues -- INV-2 loses nothing
    assert set(page.tags) == {"roll", "dr-hard"}
    assert set(page.sources) == {"rel/report.md", "/abs/report.md"}
    assert page.updated == "2026-05-31T11:00:00"


def test_quality_score_reflects_the_merged_body_not_the_new_chunk(tmp_path):
    """Closing a lead with a one-line note must not demote a rich page.

    score_page() saw only the incoming chunk and ingest overwrote the stored
    score with it, so a 113-char housekeeping update dropped well-sourced pages
    to 40 (under-120 -30, no-source-marker -20, generic-tags -10).
    """
    p = OmxPaths(root=tmp_path)
    rich = ("Measured 2026-08-04 in analysis diagnose-20260804-132500: att_norm ss_error "
            "0.4968 -> 0.6644 deg between model_7500 and model_9000, a 34 percent "
            "degradation that every training-side metric missed by under 1 percent.")
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Roll heavy-tail",
                            content=rich, tags=["roll", "heavy-tail"], category="pattern",
                            confidence="high", sources=["s1"], quality_score=100)
    assert storage.read_page(p, "roll_heavy_tail.md").quality_score >= 80

    ingest.ingest_knowledge(p, now="2026-05-31T11:00:00", title="Roll heavy-tail",
                            content="2026-08-14 curation: status set to resolved.",
                            tags=["roll"], category="pattern", confidence="high",
                            sources=["s1"], status="resolved", quality_score=40,
                            quality_reasons=("body-under-120-chars",))

    page = storage.read_page(p, "roll_heavy_tail.md")
    assert page.status == "resolved"
    assert page.quality_score >= 80, "a terse close must not demote the page"
    assert "body-under-120-chars" not in page.quality_reasons


def test_returns_the_score_the_page_actually_carries(tmp_path):
    """The CLI prints ingest's score, so it must be the stored one, not the chunk's."""
    p = OmxPaths(root=tmp_path)
    rich = ("Measured 2026-08-04 in analysis diagnose-20260804-132500: att_norm ss_error "
            "0.4968 -> 0.6644 deg between model_7500 and model_9000, a 34 percent swing.")
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Roll heavy-tail",
                            content=rich, tags=["roll", "heavy-tail"], category="pattern",
                            confidence="high", sources=["s1"], quality_score=100)
    res = ingest.ingest_knowledge(p, now="2026-05-31T11:00:00", title="Roll heavy-tail",
                                  content="2026-08-14 curation: closed.", tags=["roll"],
                                  category="pattern", confidence="high", sources=["s1"],
                                  quality_score=40, quality_reasons=("body-under-120-chars",))
    page = storage.read_page(p, "roll_heavy_tail.md")
    assert res["quality_score"] == page.quality_score
    assert res["quality_reasons"] == list(page.quality_reasons)
    assert res["quality_score"] >= 80
