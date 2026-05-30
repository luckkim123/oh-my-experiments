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


class TensorboardAdapter(IngestAdapter):
    def can_handle(self, path) -> bool:
        return "events.out.tfevents" in Path(path).name

    def ingest(self, path) -> IngestResult:
        path = Path(path)
        if not path.exists():
            raise OmxError(f"TB event file not found: {path}")
        try:
            from tensorboard.backend.event_processing import event_accumulator
        except ImportError as e:  # loud, actionable
            raise OmxError(
                "tensorboard not installed; `pip install omx-core[analyze]` to ingest TB"
            ) from e
        ea = event_accumulator.EventAccumulator(
            str(path), size_guidance={event_accumulator.SCALARS: 0})
        ea.Reload()
        tags = ea.Tags().get("scalars", [])
        series = {}
        for tag in tags:
            events = ea.Scalars(tag)
            series[tag] = np.array([e.value for e in events], dtype=float)
            series[f"_step/{tag}"] = np.array([e.step for e in events], dtype=float)
        return IngestResult(
            summary=[], series=series,
            meta={"source": str(path), "format": "tensorboard", "n_tags": len(tags)},
        )
