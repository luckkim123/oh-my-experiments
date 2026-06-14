from omx_core.omx_paths import OmxPaths
from omx_core.wiki import ingest, lint


def test_lint_clean_wiki_has_no_issues(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="A",
                            content="body", tags=["roll"], category="pattern",
                            confidence="high", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=10240)
    assert res["stats"]["total_pages"] == 1
    types = {i["type"] for i in res["issues"]}
    assert "stale" not in types and "broken-frontmatter" not in types


def test_lint_flags_broken_reference(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="A",
                            content="see [[Ghost Page]] which does not exist",
                            tags=[], category="pattern", confidence="high", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=10240)
    assert any(i["type"] == "broken-ref" for i in res["issues"])


def test_lint_flags_stale(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-01-01T10:00:00", title="Old",
                            content="body", tags=[], category="pattern",
                            confidence="high", sources=[])
    # now is ~150 days later
    res = lint.lint_wiki(p, now="2026-05-31T10:00:00", stale_days=30, max_page_size=10240)
    assert any(i["type"] == "stale" for i in res["issues"])


def test_lint_flags_oversized(tmp_path):
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Big",
                            content="x" * 200, tags=[], category="pattern",
                            confidence="high", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=50)
    assert any(i["type"] == "oversized" for i in res["issues"])


def test_lint_flags_broken_frontmatter(tmp_path):
    p = OmxPaths(root=tmp_path)
    p.wiki_dir().mkdir(parents=True, exist_ok=True)
    (p.wiki_dir() / "broken.md").write_text("no frontmatter", encoding="utf-8")
    res = lint.lint_wiki(p, now="2026-05-31T10:00:00", stale_days=30, max_page_size=10240)
    assert any(i["type"] == "broken-frontmatter" and i["slug"] == "broken.md"
               for i in res["issues"])


def test_lint_orphan_is_inbound_zero(tmp_path):
    # New definition: orphan = nobody links to it (inbound==0), even if it links OUT.
    # A links to B; A itself has no inbound -> A is now an orphan. C is isolated -> orphan.
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-01-01T10:00:00", title="A",
                            content="see [[B]] for more", tags=[], category="pattern",
                            confidence="high", sources=[])
    ingest.ingest_knowledge(p, now="2026-01-01T10:00:00", title="B",
                            content="body of B", tags=[], category="pattern",
                            confidence="high", sources=[])
    ingest.ingest_knowledge(p, now="2026-01-01T10:00:00", title="C",
                            content="isolated body", tags=[], category="pattern",
                            confidence="high", sources=[])
    # now is well past stale_days/2 so no fresh-exemption applies
    res = lint.lint_wiki(p, now="2026-05-31T10:00:00", stale_days=30, max_page_size=10240)
    orphans = {i["slug"] for i in res["issues"] if i["type"] == "orphan"}
    assert "a.md" in orphans          # outbound-only, no inbound -> orphan (NEW behavior)
    assert "c.md" in orphans          # isolated -> orphan
    assert "b.md" not in orphans      # linked-to (inbound) -> not orphan


def test_lint_fresh_page_exempt_from_orphan(tmp_path):
    # A page created within stale_days/2 of now is NOT an orphan yet (still growing).
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="New",
                            content="brand new isolated page", tags=[], category="pattern",
                            confidence="high", sources=[])
    # now is 5 days later; stale_days=30 -> half=15 -> 5 < 15 -> exempt
    res = lint.lint_wiki(p, now="2026-06-05T10:00:00", stale_days=30, max_page_size=10240)
    orphans = {i["slug"] for i in res["issues"] if i["type"] == "orphan"}
    assert "new.md" not in orphans


def test_lint_old_isolated_page_is_orphan_despite_exemption(tmp_path):
    # A page older than stale_days/2 and isolated IS an orphan (exemption does not apply).
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-01-01T10:00:00", title="Old",
                            content="old isolated page", tags=[], category="pattern",
                            confidence="high", sources=[])
    res = lint.lint_wiki(p, now="2026-03-01T10:00:00", stale_days=30, max_page_size=10240)
    orphans = {i["slug"] for i in res["issues"] if i["type"] == "orphan"}
    assert "old.md" in orphans


def test_lint_flags_contradiction_candidate_shared_tag_high_confidence(tmp_path):
    # Two HIGH-confidence pages sharing a tag -> one contradiction-candidate (a-1).
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Alpha is a floor",
                            content="alpha bounds feasibility", tags=["alpha"],
                            category="decision", confidence="high", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Alpha is a lever",
                            content="alpha expands DR range", tags=["alpha"],
                            category="decision", confidence="high", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=10240)
    cands = [i for i in res["issues"] if i["type"] == "contradiction-candidate"]
    assert len(cands) == 1
    assert cands[0]["severity"] == "info"
    assert "alpha" in cands[0]["message"]


def test_lint_no_contradiction_candidate_when_not_all_high(tmp_path):
    # Shared tag but one page is medium -> NOT a contradiction candidate (a-1 needs all-high).
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="A1", content="x",
                            tags=["alpha"], category="decision", confidence="high", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="A2", content="y",
                            tags=["alpha"], category="decision", confidence="medium", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=10240)
    assert not any(i["type"] == "contradiction-candidate" and "shared" in i["message"]
                   for i in res["issues"])


def test_lint_flags_contradiction_candidate_tag_across_categories(tmp_path):
    # Same tag in two DIFFERENT categories -> contradiction-candidate (a-2).
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="D", content="x",
                            tags=["roll"], category="decision", confidence="medium", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="B", content="y",
                            tags=["roll"], category="debugging", confidence="medium", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=10240)
    assert any(i["type"] == "contradiction-candidate" and "categor" in i["message"]
               for i in res["issues"])


def test_lint_survives_aware_timestamp_in_updated(tmp_path):
    # A page hand-edited (or written by a future tool) with a tz-AWARE `updated:`
    # field must NOT crash lint's naive `now` stale-delta; lint stays the robust
    # auditor and still flags the page as stale (FINAL-review robustness fix).
    p = OmxPaths(root=tmp_path)
    p.wiki_dir().mkdir(parents=True, exist_ok=True)
    page = (
        "---\n"
        'title: "Aware"\n'
        "tags: []\n"
        "created: 2026-01-01T10:00:00+00:00\n"
        "updated: 2026-01-01T10:00:00+00:00\n"
        "sources: []\n"
        "links: []\n"
        "category: pattern\n"
        "confidence: high\n"
        "schemaVersion: 1\n"
        "---\n"
        "body\n"
    )
    (p.wiki_dir() / "aware.md").write_text(page, encoding="utf-8")
    # now is naive, ~150 days later -> must compute without TypeError and flag stale
    res = lint.lint_wiki(p, now="2026-05-31T10:00:00", stale_days=30, max_page_size=10240)
    assert any(i["type"] == "stale" and i["slug"] == "aware.md" for i in res["issues"])


def test_lint_flags_low_confidence(tmp_path):
    # A confidence='low' page is flagged as low-confidence (info) for review/strengthening.
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Shaky",
                            content="unverified hunch", tags=[], category="pattern",
                            confidence="low", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=10240)
    lows = [i for i in res["issues"] if i["type"] == "low-confidence"]
    assert len(lows) == 1
    assert lows[0]["slug"] == "shaky.md"
    assert lows[0]["severity"] == "info"


def test_lint_high_and_medium_not_low_confidence(tmp_path):
    # high and medium confidence pages are NOT flagged low-confidence.
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="Solid", content="x",
                            tags=[], category="pattern", confidence="high", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="OK", content="y",
                            tags=[], category="pattern", confidence="medium", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=10240)
    assert not any(i["type"] == "low-confidence" for i in res["issues"])


def test_lint_flags_near_duplicate_slug_token_overlap(tmp_path):
    # Two pages whose title-derived slugs share most tokens are a near-duplicate
    # candidate (INV-1: a SIGNAL for review, not a verdict). This is the exact
    # failure mode that produced coexisting pages: the same knowledge re-added
    # under an evolved title forks the slug instead of merging.
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00",
                            title="engine gap eval adapter covers static segmented periodic",
                            content="a", tags=[], category="reference", confidence="high", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00",
                            title="engine gap eval adapter only covers static periodic",
                            content="b", tags=[], category="reference", confidence="high", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=10240)
    dups = [i for i in res["issues"] if i["type"] == "near-duplicate"]
    assert len(dups) == 1
    assert dups[0]["severity"] == "info"
    # the message names BOTH slugs so a reviewer can read both bodies
    assert "engine_gap_eval_adapter" in dups[0]["message"]


def test_lint_near_duplicate_catches_real_truncated_slug_pair(tmp_path):
    # Regression for the field case: real slugs are truncated to 64 chars by
    # title_to_slug, so an evolved-title duplicate carries divergent tail-noise
    # tokens that inflate the union. This exact on-disk pair shares 7 content
    # tokens yet scores jaccard 0.583 — the detector MUST still flag it (a 0.6
    # bar silently missed it). Operates on the slug tokens, so we exercise the
    # helper directly with the real slugs rather than synthetic clean titles.
    from omx_core.wiki.lint import _near_duplicate_candidates

    class _P:  # minimal stand-in: _near_duplicate_candidates only reads dict keys
        pass

    a = "engine_gap_eval_adapter_covers_static_segmented_periodic_still_u.md"
    b = "engine_gap_eval_adapter_only_covers_static_periodic_unsupported_.md"
    pages = {a: _P(), b: _P()}
    dups = _near_duplicate_candidates(pages)
    assert len(dups) == 1
    assert dups[0]["type"] == "near-duplicate"
    assert dups[0]["severity"] == "info"


def test_lint_no_near_duplicate_for_unrelated_pages(tmp_path):
    # Pages on different topics (few shared slug tokens) are NOT near-duplicates.
    p = OmxPaths(root=tmp_path)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="doraemon curriculum levers",
                            content="x", tags=[], category="reference", confidence="high", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="encoder dead latent dims",
                            content="y", tags=[], category="reference", confidence="high", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=10240)
    assert not any(i["type"] == "near-duplicate" for i in res["issues"])


def test_lint_near_duplicate_reports_each_pair_once(tmp_path):
    # Three mutually-similar pages must not spam one issue per ordered pair;
    # at most one issue per unordered pair, deterministic by sorted slug.
    p = OmxPaths(root=tmp_path)
    for suffix in ["roll drives heavy tail crossover",
                   "roll drives heavy tail crossover early",
                   "roll drives heavy tail crossover late"]:
        ingest.ingest_knowledge(p, now="2026-05-31T10:00:00",
                                title=f"attitude per axis cv {suffix}",
                                content="z", tags=[], category="reference",
                                confidence="high", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=10240)
    dups = [i for i in res["issues"] if i["type"] == "near-duplicate"]
    # 3 mutually-similar pages -> at most C(3,2)=3 unordered pairs, never 6 ordered
    assert 1 <= len(dups) <= 3
