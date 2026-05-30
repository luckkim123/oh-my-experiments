"""omx_core.reduce.summarize — long-form records -> exact aggregates.

The repo's mandatory rule (03-analysis-quality): CV = ss_error_std / ss_error,
computed per (dr_level, axis). Exact arithmetic via pandas, never LLM mental math.
"""
import numpy as np
import pandas as pd

from omx_core.ingest.base import SummaryRecord


def to_dataframe(records) -> pd.DataFrame:
    """list[SummaryRecord] -> tidy DataFrame [dr_level, axis, field, value]."""
    return pd.DataFrame(
        [(r.dr_level, r.axis, r.field, r.value) for r in records],
        columns=["dr_level", "axis", "field", "value"],
    )


def add_cv(df: pd.DataFrame, base_field: str, std_field: str | None = None) -> pd.DataFrame:
    """Per (dr_level, axis), CV = std/mean for base_field.

    Returns one row per (dr_level, axis) that has BOTH base_field and its std,
    with columns [dr_level, axis, mean, std, cv]. 0/0 -> nan (never raises).
    """
    std_field = std_field or f"{base_field}_std"
    base = df[df.field == base_field][["dr_level", "axis", "value"]].rename(
        columns={"value": "mean"})
    std = df[df.field == std_field][["dr_level", "axis", "value"]].rename(
        columns={"value": "std"})
    merged = base.merge(std, on=["dr_level", "axis"], how="inner")
    # 0/0 -> nan; x/0 -> inf (numpy default with divide guard)
    with np.errstate(divide="ignore", invalid="ignore"):
        merged["cv"] = merged["std"] / merged["mean"]
    return merged
