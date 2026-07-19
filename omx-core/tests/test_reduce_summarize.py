import math

import pandas as pd
from omx_core.ingest import SummaryRecord
from omx_core.reduce.summarize import add_cv, to_dataframe


def _recs():
    return [
        SummaryRecord("none", "roll", "ss_error", 0.76),
        SummaryRecord("none", "roll", "ss_error_std", 0.48),
        SummaryRecord("none", "pitch", "ss_error", 0.20),
        SummaryRecord("none", "pitch", "ss_error_std", 0.00),  # mean nonzero, std zero
        SummaryRecord("none", None, "survival_pct", 100.0),
    ]


def test_to_dataframe_columns():
    df = to_dataframe(_recs())
    assert list(df.columns) == ["dr_level", "axis", "field", "value"]
    assert len(df) == 5


def test_to_dataframe_keeps_none_axis():
    df = to_dataframe(_recs())
    surv = df[df.field == "survival_pct"]
    assert surv.iloc[0]["axis"] is None or pd.isna(surv.iloc[0]["axis"])


def test_add_cv_computes_std_over_mean():
    df = to_dataframe(_recs())
    cv = add_cv(df, base_field="ss_error")
    roll = cv[(cv.axis == "roll")].iloc[0]
    assert math.isclose(roll["cv"], 0.48 / 0.76, rel_tol=1e-9)
    pitch = cv[(cv.axis == "pitch")].iloc[0]
    assert pitch["cv"] == 0.0                       # std 0 over mean 0.20


def test_add_cv_zero_mean_is_nan():
    recs = [SummaryRecord("none", "vx", "ss_error", 0.0),
            SummaryRecord("none", "vx", "ss_error_std", 0.0)]
    cv = add_cv(to_dataframe(recs), base_field="ss_error")
    assert math.isnan(cv.iloc[0]["cv"])            # 0/0 -> nan, never raise


def test_add_cv_only_for_axes_with_both_fields():
    # att_norm-style: has ss_error + ss_error_std -> CV present
    recs = [SummaryRecord("hard", "att_norm", "ss_error", 0.30),
            SummaryRecord("hard", "att_norm", "ss_error_std", 0.13)]
    cv = add_cv(to_dataframe(recs), base_field="ss_error")
    assert len(cv) == 1
    assert math.isclose(cv.iloc[0]["cv"], 0.13 / 0.30, rel_tol=1e-9)
