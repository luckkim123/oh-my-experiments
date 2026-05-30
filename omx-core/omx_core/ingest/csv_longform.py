"""omx_core.ingest.csv_longform — flat long-form CSV adapter.

Expects columns: dr_level, axis, field, value. A blank axis cell -> axis=None
(run-level scalar). Proves the IngestAdapter abstraction across a second,
genuinely different input format (parsing) with the same SummaryRecord output.
"""
import csv
from pathlib import Path

from omx_core.ingest.base import IngestAdapter, IngestResult, SummaryRecord

_REQUIRED = {"dr_level", "axis", "field", "value"}


class LongFormCsvAdapter(IngestAdapter):
    def can_handle(self, path: Path) -> bool:
        return Path(path).suffix == ".csv"

    def ingest(self, path: Path) -> IngestResult:
        path = Path(path)
        with path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            header = set(reader.fieldnames or [])
            missing = _REQUIRED - header
            if missing:
                raise ValueError(f"CSV {path} missing required columns: {sorted(missing)}")
            records = []
            for row in reader:
                axis = row["axis"] if row["axis"] else None
                records.append(
                    SummaryRecord(row["dr_level"], axis, row["field"], float(row["value"]))
                )
        return IngestResult(
            summary=records, series={},
            meta={"source": str(path), "format": "csv_longform"},
        )
