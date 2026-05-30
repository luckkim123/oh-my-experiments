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
