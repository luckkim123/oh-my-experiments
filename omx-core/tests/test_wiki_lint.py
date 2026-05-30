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


def test_lint_orphan_only_when_no_links_either_direction(tmp_path):
    p = OmxPaths(root=tmp_path)
    # A links to B; C is isolated (no outbound, no inbound)
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="A",
                            content="see [[B]] for more", tags=[], category="pattern",
                            confidence="high", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="B",
                            content="body of B", tags=[], category="pattern",
                            confidence="high", sources=[])
    ingest.ingest_knowledge(p, now="2026-05-31T10:00:00", title="C",
                            content="isolated body", tags=[], category="pattern",
                            confidence="high", sources=[])
    res = lint.lint_wiki(p, now="2026-05-31T10:01:00", stale_days=30, max_page_size=10240)
    orphans = {i["slug"] for i in res["issues"] if i["type"] == "orphan"}
    assert "c.md" in orphans          # isolated -> orphan
    assert "a.md" not in orphans      # has outbound link -> not orphan
    assert "b.md" not in orphans      # is linked-to (inbound) -> not orphan
