"""omx_core.wiki — Claude-free keyword-indexed knowledge layer (build #8).

Re-implements OMC's wiki in Python (pattern, not import). The core does pure
deterministic IO/search/audit; the wall-clock `now` is injected by callers.
"""
from omx_core.wiki.types import WikiError, WikiPage
from omx_core.wiki.ingest import ingest_knowledge
from omx_core.wiki.query import query_wiki, tokenize
from omx_core.wiki.lint import lint_wiki
from omx_core.wiki import storage

__all__ = [
    "WikiError", "WikiPage", "ingest_knowledge", "query_wiki",
    "tokenize", "lint_wiki", "storage",
]
