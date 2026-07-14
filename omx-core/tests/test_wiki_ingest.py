import pytest

from omx_core.omx_paths import OmxPaths
from omx_core.wiki.types import WikiError
from omx_core.wiki import ingest, storage


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
