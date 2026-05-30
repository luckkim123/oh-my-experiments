"""omx_core.ingest.base — normalized ingest containers + adapter contract.

Every source (eval_dr summary.json, CSV, WandB, TB) is normalized into ONE
container, IngestResult, so the reduce layer never learns a source format.
- summary: long-form tidy rows (dr_level, axis, field, value) for exact stats.
- series:  named time-series arrays (trajectories, training curves) for plots.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class SummaryRecord:
    """One scalar observation. axis=None marks a run-level scalar (e.g. survival_pct)."""
    dr_level: str
    axis: Optional[str]
    field: str
    value: float


@dataclass
class IngestResult:
    """Normalized output of any adapter. All three members default to empty."""
    summary: list = dc_field(default_factory=list)        # list[SummaryRecord]
    series: dict = dc_field(default_factory=dict)          # dict[str, np.ndarray]
    meta: dict = dc_field(default_factory=dict)            # source path, format, run_id, ...


class IngestAdapter(ABC):
    """Source -> IngestResult. Subclasses implement can_handle + ingest."""

    @abstractmethod
    def can_handle(self, path: Path) -> bool:
        """Cheap check (extension / sentinel filename) — no full parse."""

    @abstractmethod
    def ingest(self, path: Path) -> IngestResult:
        """Parse `path` into a normalized IngestResult. Loud-fail on malformed input."""
