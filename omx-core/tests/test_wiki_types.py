from omx_core.wiki.types import (
    WikiError,
    WikiPage,
    CATEGORIES,
    CONFIDENCES,
    WIKI_SCHEMA_VERSION,
    RESERVED_FILES,
)


def test_wiki_error_is_omx_error():
    from omx_core.omx_paths import OmxError
    assert issubclass(WikiError, OmxError)


def test_categories_are_the_eight_domain_neutral_ones():
    assert CATEGORIES == frozenset({
        "architecture", "decision", "pattern", "debugging",
        "environment", "session-log", "reference", "convention",
    })


def test_confidences():
    assert CONFIDENCES == ("high", "medium", "low")


def test_reserved_files():
    assert RESERVED_FILES == frozenset({"index.md", "log.md", "profile.md"})


def test_wikipage_holds_frontmatter_and_content():
    page = WikiPage(
        slug="roll-heavy-tail.md",
        title="Roll heavy-tail",
        tags=["roll", "heavy-tail"],
        created="2026-05-31T10:00:00",
        updated="2026-05-31T10:00:00",
        sources=["20260531-100000-compare"],
        links=["other-slug"],
        category="pattern",
        confidence="high",
        schema_version=1,
        content="some markdown",
    )
    assert page.title == "Roll heavy-tail"
    assert page.category == "pattern"
    assert page.tags == ["roll", "heavy-tail"]
