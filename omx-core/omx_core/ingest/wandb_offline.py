"""omx_core.ingest.wandb_offline — WandB adapter, LOCAL OFFLINE logs only (build #4).

User decision 2026-05-30: WandB source = the on-disk `run-*.wandb` transaction log,
parsed via wandb.sdk.internal.datastore -- NO network, NO auth, NO wandb.Api. This
keeps the core Claude-free AND deterministic (unit tests read a committed fixture).
History scalars become IngestResult.series (curves). wandb is an OPTIONAL dep
(extra 'analyze'), imported inside ingest().
"""
from collections import defaultdict
from pathlib import Path

import numpy as np

from omx_core.ingest.base import IngestAdapter, IngestResult
from omx_core.omx_paths import OmxError


class WandbAdapter(IngestAdapter):
    def can_handle(self, path) -> bool:
        p = str(path)
        if p.startswith("wandb://") or p.endswith(".wandb"):
            return True
        d = Path(p)
        return d.is_dir() and any(d.glob("*.wandb"))

    def _resolve(self, path) -> Path:
        """Map a wandb:// pointer or a path to the concrete .wandb file.

        wandb://<x> strips the scheme. If the result is a directory, it must
        contain exactly one .wandb file (the run log)."""
        raw = str(path)
        p = Path(raw[len("wandb://"):]) if raw.startswith("wandb://") else Path(raw)
        if p.is_dir():
            logs = sorted(p.glob("*.wandb"))
            if len(logs) != 1:
                raise OmxError(f"expected exactly one .wandb under {p}, found {len(logs)}")
            return logs[0]
        return p

    def ingest(self, path) -> IngestResult:
        wf = self._resolve(path)
        if not wf.exists():
            raise OmxError(f"wandb offline log not found: {wf}")
        try:
            from wandb.sdk.internal import datastore
            from wandb.proto import wandb_internal_pb2 as pb
        except ImportError as e:
            raise OmxError(
                "wandb not installed; `pip install omx-core[analyze]` to ingest wandb logs"
            ) from e
        ds = datastore.DataStore()
        ds.open_for_scan(str(wf))
        cols = defaultdict(list)
        step_cols = defaultdict(list)
        try:
            while True:
                data = ds.scan_data()
                if data is None:
                    break
                rec = pb.Record()
                rec.ParseFromString(data)
                if rec.WhichOneof("record_type") != "history":
                    continue
                step = float(rec.history.step.num)
                for item in rec.history.item:
                    key = item.key or "/".join(item.nested_key)
                    if not key:
                        continue
                    try:
                        value = float(item.value_json)
                    except (ValueError, TypeError):
                        # non-numeric history values (strings/objects) are not curves; skip
                        continue
                    cols[key].append(value)
                    # Append the step only on a successful parse so the _step companion
                    # stays index-aligned with the value series (TB adapter contract).
                    step_cols[key].append(step)
        finally:
            ds.close()
        if not cols:
            raise OmxError(f"no numeric history scalars in wandb log {wf}")
        # Mirror the TB adapter: emit a _step/<key> companion (the logged history
        # step) so omx plot puts wandb curves on the same global-step x-axis as TB.
        series = {k: np.array(v, dtype=float) for k, v in cols.items()}
        for k, steps in step_cols.items():
            series[f"_step/{k}"] = np.array(steps, dtype=float)
        return IngestResult(
            summary=[], series=series,
            # n_keys counts metric series only (excludes the _step/<key> companions),
            # matching the TB adapter's n_tags convention.
            meta={"source": str(wf), "format": "wandb_offline", "n_keys": len(cols)},
        )
