from omx_core.ingest import IngestResult
from omx_core.ingest.eval_summary import EvalSummaryAdapter


def test_can_handle_summary_json(fixtures_dir):
    a = EvalSummaryAdapter()
    assert a.can_handle(fixtures_dir / "summary.json") is True
    assert a.can_handle(fixtures_dir / "data_none.npz") is False


def test_ingest_returns_ingest_result(fixtures_dir):
    res = EvalSummaryAdapter().ingest(fixtures_dir / "summary.json")
    assert isinstance(res, IngestResult)
    assert res.series == {}                      # eval-summary is tabular only
    assert res.meta["format"] == "eval_summary"


def test_record_count_matches_schema(fixtures_dir):
    # 2 levels x (2 full axes x 15 fields + att_norm x 4 fields + survival_pct x 1)
    # per level = 30 + 4 + 1 = 35 ; total = 70
    res = EvalSummaryAdapter().ingest(fixtures_dir / "summary.json")
    assert len(res.summary) == 70


def test_axis_field_extracted_exactly(fixtures_dir):
    res = EvalSummaryAdapter().ingest(fixtures_dir / "summary.json")
    rec = [r for r in res.summary
           if r.dr_level == "none" and r.axis == "roll" and r.field == "ss_error"]
    assert len(rec) == 1
    assert rec[0].value == 0.76


def test_att_norm_asymmetry_handled(fixtures_dir):
    # att_norm must yield exactly its 4 present fields, not 15
    res = EvalSummaryAdapter().ingest(fixtures_dir / "summary.json")
    att = [r for r in res.summary if r.dr_level == "none" and r.axis == "att_norm"]
    assert {r.field for r in att} == {"ss_error", "ss_error_std", "ss_jitter", "ss_jitter_std"}


def test_survival_pct_is_run_level_scalar(fixtures_dir):
    res = EvalSummaryAdapter().ingest(fixtures_dir / "summary.json")
    surv = [r for r in res.summary if r.field == "survival_pct"]
    assert len(surv) == 2                          # one per level
    assert all(r.axis is None for r in surv)
    assert all(r.value == 100.0 for r in surv)


def test_malformed_json_raises(tmp_path):
    bad = tmp_path / "summary.json"
    bad.write_text("{not valid json")
    import pytest
    with pytest.raises(Exception):
        EvalSummaryAdapter().ingest(bad)
