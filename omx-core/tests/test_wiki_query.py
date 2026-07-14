from omx_core.omx_paths import OmxPaths
from omx_core.wiki import ingest, query


def test_tokenize_latin_and_digits():
    toks = query.tokenize("Roll Heavy-Tail 42")
    assert "roll" in toks and "heavy" in toks and "tail" in toks and "42" in toks


def test_tokenize_korean_bigrams_and_singletons():
    toks = query.tokenize("롤축")
    assert "롤" in toks and "축" in toks   # singletons
    assert "롤축" in toks                  # bigram


def test_query_empty_wiki_returns_zero(tmp_path):
    p = OmxPaths(root=tmp_path)
    res = query.query_wiki(p, now="2026-05-31T10:00:00", text="anything")
    assert res["n_matches"] == 0
    assert res["matches"] == []
    assert res["corrupt_pages"] == []


def test_query_scores_title_over_content(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Heavy tail",
                            content="unrelated body text", tags=[],
                            category="pattern", confidence="high", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Other",
                            content="this body mentions heavy tail once", tags=[],
                            category="pattern", confidence="high", sources=[])
    res = query.query_wiki(p, now="2026-05-31T10:01:00", text="heavy tail")
    assert res["n_matches"] == 2
    assert res["matches"][0]["title"] == "Heavy tail"   # title match outranks content


def test_query_tag_match_boosts(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="A",
                            content="body", tags=["roll"], category="pattern",
                            confidence="high", sources=[])
    res = query.query_wiki(p, now="2026-05-31T10:01:00", text="roll", tags=["roll"])
    assert res["n_matches"] == 1
    assert res["matches"][0]["slug"] == "a.md"


def test_query_match_dict_includes_status(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Heavy tail",
                            content="body", tags=[], category="pattern",
                            confidence="high", sources=[], status="needs-experiment")
    res = query.query_wiki(p, now="2026-05-31T10:01:00", text="heavy tail")
    assert res["matches"][0]["status"] == "needs-experiment"


def test_enumerate_pages_all_and_status_filtered(tmp_path):
    # deterministic no-scoring catalog; backs both `wiki list` and the queue-launch gate.
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Lead", content="b",
                            tags=[], category="reference", confidence="high", sources=[],
                            status="needs-experiment")
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Plain", content="b",
                            tags=[], category="reference", confidence="high", sources=[])
    allp = query.enumerate_pages(p)
    assert len(allp["pages"]) == 2 and allp["corrupt_pages"] == []
    only = query.enumerate_pages(p, status="needs-experiment")
    assert [pg["slug"] for pg in only["pages"]] == ["lead.md"]
    assert only["pages"][0]["blocked_on"] is None


def test_query_reports_corrupt_page_and_skips_it(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Good",
                            content="heavy tail here", tags=[], category="pattern",
                            confidence="high", sources=[])
    # write a corrupt page directly (no frontmatter)
    p.wiki_dir().mkdir(parents=True, exist_ok=True)
    (p.wiki_dir() / "broken.md").write_text("no frontmatter at all", encoding="utf-8")
    res = query.query_wiki(p, now="2026-05-31T10:01:00", text="heavy")
    assert "broken.md" in res["corrupt_pages"]
    assert any(m["slug"] == "good.md" for m in res["matches"])  # good page still found


def test_query_n_matches_is_total_not_truncated(tmp_path):
    p = OmxPaths(root=tmp_path)
    for i in range(25):
        ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title=f"Heavy tail {i}",
                                content="heavy tail body", tags=[], category="pattern",
                                confidence="high", sources=[])
    res = query.query_wiki(p, now="2026-05-31T10:01:00", text="heavy tail", limit=20)
    assert res["n_matches"] == 25      # total that matched
    assert res["n_returned"] == 20     # capped by limit
    assert len(res["matches"]) == 20


def test_query_low_confidence_sinks_below_equal_keyword_high(tmp_path):
    # same keyword content, different confidence -> high ranks first (was a tie).
    # NOTE: second title is "Heavy tail 2", not a literal duplicate of the first --
    # ingest_knowledge merges same-slug pages (INV-2 append-merge, ingest.py:59-109)
    # and merge always keeps the higher confidence, so an identical title here would
    # collapse both ingests into one "high"-confidence page (n_matches==1, no tie to
    # rank). "Heavy tail 2" still contains "heavy tail" as a substring so it earns the
    # same +5 title-match score, keeping the tie while landing on a distinct slug.
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Heavy tail",
                            content="body", tags=[], category="pattern",
                            confidence="low", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Heavy tail 2",
                            content="body", tags=[], category="pattern",
                            confidence="high", sources=[])
    res = query.query_wiki(p, now="2026-05-31T10:01:00", text="heavy tail")
    assert res["n_matches"] == 2
    assert res["matches"][0]["confidence"] == "high"   # high wins the tie
    assert res["matches"][1]["confidence"] == "low"


def test_query_strong_keyword_low_still_outranks_weak_high(tmp_path):
    # low-confidence TITLE match: title 'Heavy tail' also embeds into content
    # (ingest heading), so real score is 7 -> weighted 7*0.80=5.6, beating the
    # high-confidence CONTENT match (score 2 -> 2.0). Keyword dominant.
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Heavy tail",
                            content="unrelated", tags=[], category="pattern",
                            confidence="low", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Other",
                            content="this mentions heavy tail once", tags=[],
                            category="pattern", confidence="high", sources=[])
    res = query.query_wiki(p, now="2026-05-31T10:01:00", text="heavy tail")
    assert res["matches"][0]["title"] == "Heavy tail"   # low+title beats high+content


def test_query_resolved_status_demoted_on_tie(tmp_path):
    # equal keyword + equal confidence; a resolved page sinks below a non-actionable one.
    # NOTE: second title is "Heavy tail 2" for the same reason as the confidence-tie
    # test above -- an identical title merges (INV-2, ingest.py:59-109) and a None
    # status on merge KEEPS the existing status, so a literal duplicate title would
    # collapse into one "resolved" page (n_matches==1) instead of two ranked pages.
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Heavy tail",
                            content="body", tags=[], category="pattern",
                            confidence="high", sources=[], status="resolved")
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Heavy tail 2",
                            content="body", tags=[], category="pattern",
                            confidence="high", sources=[])
    res = query.query_wiki(p, now="2026-05-31T10:01:00", text="heavy tail")
    assert res["matches"][0]["status"] is None       # active page first
    assert res["matches"][1]["status"] == "resolved"  # resolved demoted


def test_query_near_tie_inversion_is_intended(tmp_path):
    # DESIGN NOTE (v0.7.1): keyword score is DOMINANT, not strictly primary.
    # For NEAR-tied scores the combined confidence+status discount intentionally
    # re-orders: a score-3 low+resolved page (3*0.80*0.70=1.68) sinks below a
    # score-2 high active page (2*1.0=2.0). This is the stub-sinking feature, not
    # a bug -- documented so a future change notices if it flips.
    p = OmxPaths(root=tmp_path)
    # content="stub" (not "tail"): ingest embeds the title as a "# Heavy" heading
    # into content, so the title alone already contributes score 3 (title +2 for
    # "heavy", content +1 for "heavy" via the heading) -- an explicit "tail" in
    # content would double-count and push the score to 4.
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Heavy",
                            content="stub", tags=[], category="pattern",
                            confidence="low", sources=[], status="resolved")
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Other",
                            content="heavy tail", tags=[], category="pattern",
                            confidence="high", sources=[])
    res = query.query_wiki(p, now="2026-05-31T10:01:00", text="heavy tail")
    assert res["n_matches"] == 2
    assert res["matches"][0]["title"] == "Other"   # score 2, weight 2.0 -- wins
    assert res["matches"][1]["title"] == "Heavy"    # score 3, weight 1.68 -- sinks
