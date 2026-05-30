"""omx_core.ingest.stubs — interface signposts for WandB / TensorBoard.

These declare the extension points (so the ABC has named network-source members)
but defer real ingestion to build #4 (exp-analyze), where they are validated on
live data. can_handle is implemented (cheap, no network); ingest loud-fails with
a build pointer rather than silently returning empty.
"""
from pathlib import Path

from omx_core.ingest.base import IngestAdapter, IngestResult


class WandbAdapter(IngestAdapter):
    def can_handle(self, path: Path) -> bool:
        return str(path).startswith("wandb://")

    def ingest(self, path: Path) -> IngestResult:
        raise NotImplementedError(
            "WandbAdapter.ingest is a deferred extension point — implemented in "
            "build #4 (exp-analyze) where WandB is validated on live data."
        )


class TensorboardAdapter(IngestAdapter):
    def can_handle(self, path: Path) -> bool:
        return "events.out.tfevents" in Path(path).name

    def ingest(self, path: Path) -> IngestResult:
        raise NotImplementedError(
            "TensorboardAdapter.ingest is a deferred extension point — implemented "
            "in build #4 (exp-analyze) where TB event files are validated."
        )
