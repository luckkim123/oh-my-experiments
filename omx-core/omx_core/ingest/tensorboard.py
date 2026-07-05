"""omx_core.ingest.tensorboard — real TB event-file adapter (build #4).

TB scalars are training/eval CURVES, so they fill IngestResult.series (named
1-D arrays), never .summary (which is long-form eval_dr stats). tensorboard is
an OPTIONAL dependency (extra 'analyze'); it is imported INSIDE ingest() so the
core stays importable without it. Uses EventAccumulator (pure-TB, no TensorFlow).
"""
from pathlib import Path

import numpy as np

from omx_core.ingest.base import IngestAdapter, IngestResult
from omx_core.omx_paths import OmxError

#: Reservoir cap for TB scalars (per tag). 0 would mean "load everything" —
#: the unbounded-ingest OOM the audit flagged (#2). Overridable per call.
MAX_SCALARS_DEFAULT = 10_000
#: Refuse to open sources larger than this without an explicit override.
MAX_INGEST_BYTES_DEFAULT = 1 << 30  # 1 GiB


def check_ingest_size(path, max_bytes) -> None:
    """st_size pre-check shared by size-bounded adapters (loud-fail OmxError)."""
    limit = MAX_INGEST_BYTES_DEFAULT if max_bytes is None else max_bytes
    size = Path(path).stat().st_size
    if size > limit:
        raise OmxError(
            f"{path} is {size} bytes, exceeds the ingest limit {limit}; "
            f"pass --max-bytes to raise it explicitly")


class TensorboardAdapter(IngestAdapter):
    def __init__(self, max_scalars=None, max_bytes=None):
        self.max_scalars = MAX_SCALARS_DEFAULT if max_scalars is None else max_scalars
        self.max_bytes = max_bytes

    def can_handle(self, path) -> bool:
        return "events.out.tfevents" in Path(path).name

    def ingest(self, path) -> IngestResult:
        path = Path(path)
        if not path.exists():
            raise OmxError(f"TB event file not found: {path}")
        check_ingest_size(path, self.max_bytes)
        try:
            from tensorboard.backend.event_processing import event_accumulator
        except ImportError as e:  # loud, actionable
            raise OmxError(
                "tensorboard not installed; `pip install omx-core[analyze]` to ingest TB"
            ) from e
        ea = event_accumulator.EventAccumulator(
            str(path), size_guidance={event_accumulator.SCALARS: self.max_scalars})
        ea.Reload()
        tags = ea.Tags().get("scalars", [])
        series = {}
        # For each scalar tag T, two series keys are written:
        #   series[T]          -- the float values
        #   series["_step/" + T] -- the corresponding global step indices (x-axis)
        for tag in tags:
            events = ea.Scalars(tag)
            series[tag] = np.array([e.value for e in events], dtype=float)
            series[f"_step/{tag}"] = np.array([e.step for e in events], dtype=float)
        return IngestResult(
            summary=[], series=series,
            meta={"source": str(path), "format": "tensorboard", "n_tags": len(tags)},
        )
