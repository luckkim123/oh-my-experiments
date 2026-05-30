import pytest
from omx_core.ingest import IngestResult, SummaryRecord
from omx_core.ingest.csv_longform import LongFormCsvAdapter


def test_can_handle_csv(fixtures_dir):
    a = LongFormCsvAdapter()
    assert a.can_handle(fixtures_dir / "metrics_long.csv") is True
    assert a.can_handle(fixtures_dir / "summary.json") is False


def test_ingest_row_count(fixtures_dir):
    res = LongFormCsvAdapter().ingest(fixtures_dir / "metrics_long.csv")
    assert isinstance(res, IngestResult)
    assert len(res.summary) == 4
    assert res.meta["format"] == "csv_longform"


def test_blank_axis_becomes_none(fixtures_dir):
    res = LongFormCsvAdapter().ingest(fixtures_dir / "metrics_long.csv")
    surv = [r for r in res.summary if r.field == "survival_pct"]
    assert len(surv) == 1
    assert surv[0].axis is None
    assert surv[0].value == 100.0


def test_value_is_float(fixtures_dir):
    res = LongFormCsvAdapter().ingest(fixtures_dir / "metrics_long.csv")
    r = [x for x in res.summary if x.dr_level == "none" and x.axis == "roll"
         and x.field == "ss_error"][0]
    assert r.value == 0.76
    assert isinstance(r.value, float)


def test_missing_required_column_raises(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("dr_level,axis,value\nnone,roll,0.1\n")  # no 'field' column
    with pytest.raises(ValueError):
        LongFormCsvAdapter().ingest(bad)
