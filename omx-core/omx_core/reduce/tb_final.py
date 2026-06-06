"""omx_core.reduce.tb_final — named final-window means for an arbitrary tag list.

A pure reduction over an already-ingested TB series dict (the shape
TensorboardAdapter.ingest returns: `tag -> values`, `_step/<tag> -> steps`).
Given a tag list and a window, return {tag: mean of its last `window` samples}.

This is the general, raw-TB-no-hand-read home for pulling per-term scalars a
report must cite by number — e.g. the 8 Reward/* decomposition terms the engine
table omitted. Keeping it here (not in the workspace engine) means every
workspace gets it, and the skill's "a numeric claim traces to a code-exec
source" rule is satisfied without eyeballing a PNG.

Discipline: a requested tag that is ABSENT (or has zero samples) is a LOUD
failure, never a silent 0 — that is exactly the "engine emitted an empty cell"
trap this whole fix exists to stop. The empty cell is a hypothesis, not a fact;
forcing a loud error here makes the caller cross-check rather than assert "none".
"""
import numpy as np

from omx_core.omx_paths import OmxError

DEFAULT_WINDOW = 200


def final_window_means(series: dict, tags, window: int = DEFAULT_WINDOW) -> dict:
    """{tag: mean of its last `window` samples} for each tag in `tags`.

    Args:
        series: dict from a TB ingest — `tag -> 1-D value array` (and parallel
            `_step/<tag>` arrays, which are ignored here).
        tags: iterable of scalar tag names to reduce.
        window: number of trailing samples to average (default 200, matching the
            repo's "last ~200 iter" convention). Clamped to the series length.

    Returns:
        {tag: float}. Empty `tags` -> {}.

    Raises:
        OmxError: window <= 0; a tag is a "_step/" key; a tag is absent from
            `series`; or a present tag has zero samples. (No silent 0/nan.)
    """
    if window <= 0:
        raise OmxError(f"window must be positive, got {window}")
    out = {}
    for tag in tags:
        if tag.startswith("_step/"):
            raise OmxError(
                f"refusing to reduce step-index key {tag!r}; pass the scalar tag, "
                f"not its _step/ companion")
        if tag not in series:
            available = sorted(t for t in series if not t.startswith("_step/"))
            raise OmxError(
                f"tag {tag!r} not in TB series; available scalar tags: {available}")
        arr = np.asarray(series[tag], dtype=float)
        if arr.size == 0:
            raise OmxError(f"tag {tag!r} has zero samples; cannot take a final-window mean")
        out[tag] = float(np.mean(arr[-window:]))
    return out
