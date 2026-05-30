"""omx_paths — the single source of truth for every OMX path.

No other module may construct an OMX path by string concatenation; all paths
come from OmxPaths getters (added in later tasks), which validate ids
(loud-fail) before returning.
"""
from __future__ import annotations


class OmxPathError(ValueError):
    """Raised on any invalid id or path-construction request (never silent)."""
