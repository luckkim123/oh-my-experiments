import pytest

from omx_core.omx_paths import OmxPaths
from omx_core.wiki.types import WikiPage, WikiError
from omx_core.wiki import storage


def _page(slug="alpha.md", title="Alpha", content="hello body"):
    return WikiPage(
        slug=slug, title=title, tags=["t1", "t2"],
        created="2026-05-31T10:00:00", updated="2026-05-31T10:00:00",
        sources=["s1"], links=["beta.md"], category="pattern",
        confidence="high", schema_version=1, content=content,
    )


def test_serialize_then_parse_round_trips(tmp_path):
    page = _page()
    text = storage.serialize_page(page)
    assert text.startswith("---\n")
    parsed = storage.parse_page("alpha.md", text)
    assert parsed.title == "Alpha"
    assert parsed.tags == ["t1", "t2"]
    assert parsed.category == "pattern"
    assert parsed.confidence == "high"
    assert parsed.sources == ["s1"]
    assert parsed.links == ["beta.md"]
    assert "hello body" in parsed.content


def test_parse_page_loud_fails_on_missing_frontmatter():
    with pytest.raises(WikiError):
        storage.parse_page("x.md", "no frontmatter here")


def test_title_to_slug_ascii():
    assert storage.title_to_slug("Roll Heavy-Tail!") == "roll_heavy_tail.md"


def test_title_to_slug_non_ascii_falls_back_to_hash():
    slug = storage.title_to_slug("롤 헤비테일")
    assert slug.startswith("page_") and slug.endswith(".md")


def test_write_then_read_page(tmp_path):
    p = OmxPaths(root=tmp_path)
    storage.write_page(p, _page(), now="2026-05-31T10:00:00")
    got = storage.read_page(p, "alpha.md")
    assert got.title == "Alpha"


def test_write_rejects_reserved_filename(tmp_path):
    p = OmxPaths(root=tmp_path)
    with pytest.raises(WikiError):
        storage.write_page(p, _page(slug="index.md"), now="2026-05-31T10:00:00")


def test_read_missing_page_returns_none(tmp_path):
    p = OmxPaths(root=tmp_path)
    assert storage.read_page(p, "nope.md") is None


def test_list_pages_excludes_reserved(tmp_path):
    p = OmxPaths(root=tmp_path)
    storage.write_page(p, _page(slug="alpha.md"), now="2026-05-31T10:00:00")
    storage.write_page(p, _page(slug="beta.md"), now="2026-05-31T10:00:00")
    assert storage.list_pages(p) == ["alpha.md", "beta.md"]


def test_title_slug_composes_with_write_read(tmp_path):
    p = OmxPaths(root=tmp_path)
    slug = storage.title_to_slug("Roll Heavy-Tail!")
    storage.write_page(p, _page(slug=slug, title="Roll Heavy-Tail!"), now="2026-05-31T10:00:00")
    assert storage.read_page(p, slug).title == "Roll Heavy-Tail!"


def test_array_element_with_comma_round_trips(tmp_path):
    page = _page()
    page = WikiPage(**{**page.__dict__, "tags": ["a,b", "c"]})
    parsed = storage.parse_page("alpha.md", storage.serialize_page(page))
    assert parsed.tags == ["a,b", "c"]


def test_array_element_with_escaped_quote_round_trips(tmp_path):
    page = _page()
    page = WikiPage(**{**page.__dict__, "tags": ['say "hi"']})
    parsed = storage.parse_page("alpha.md", storage.serialize_page(page))
    assert parsed.tags == ['say "hi"']
