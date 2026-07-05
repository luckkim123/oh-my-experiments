"""omx_core.ingest.eval_summary — eval_dr summary.json adapter.

Schema (verified): {dr_level: {axis: {field: float}}} where one member of each
level (survival_pct) is a bare float, not a dict, and att_norm carries a subset
of fields. Flattened to long-form SummaryRecords; survival_pct -> axis=None.
"""
import json
from pathlib import Path

from omx_core.ingest.base import IngestAdapter, IngestResult, SummaryRecord
from omx_core.ingest.tensorboard import check_ingest_size


class EvalSummaryAdapter(IngestAdapter):
    def __init__(self, max_bytes=None):
        self.max_bytes = max_bytes

    def can_handle(self, path: Path) -> bool:
        return Path(path).name == "summary.json"

    def ingest(self, path: Path) -> IngestResult:
        path = Path(path)
        check_ingest_size(path, self.max_bytes)
        data = json.loads(path.read_text())  # loud-fail on malformed JSON
        records = []
        for dr_level, level_body in data.items():
            for key, member in level_body.items():
                if isinstance(member, dict):          # an axis dict (roll, ..., att_norm)
                    for field_name, value in member.items():
                        records.append(SummaryRecord(dr_level, key, field_name, float(value)))
                else:                                 # a run-level scalar (survival_pct)
                    records.append(SummaryRecord(dr_level, None, key, float(member)))
        return IngestResult(
            summary=records,
            series={},
            meta={"source": str(path), "format": "eval_summary"},
        )
