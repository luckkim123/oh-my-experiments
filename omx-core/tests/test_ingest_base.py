import numpy as np
import pytest
from omx_core.ingest import IngestAdapter, IngestResult, SummaryRecord


def test_summary_record_is_frozen():
    r = SummaryRecord(dr_level="none", axis="roll", field="ss_error", value=0.5)
    with pytest.raises(Exception):
        r.value = 9.0  # frozen dataclass


def test_summary_record_axis_may_be_none_for_run_level_scalar():
    r = SummaryRecord(dr_level="none", axis=None, field="survival_pct", value=100.0)
    assert r.axis is None
    assert r.field == "survival_pct"


def test_ingest_result_defaults_are_independent():
    a = IngestResult()
    b = IngestResult()
    a.summary.append(SummaryRecord("none", "roll", "ss_error", 0.1))
    a.series["x"] = np.arange(3)
    a.meta["k"] = "v"
    assert b.summary == [] and b.series == {} and b.meta == {}  # no shared mutable default


def test_adapter_is_abstract():
    with pytest.raises(TypeError):
        IngestAdapter()  # cannot instantiate ABC with abstract methods


def test_concrete_adapter_must_implement_both_methods():
    class Half(IngestAdapter):
        def can_handle(self, path):  # missing ingest()
            return True
    with pytest.raises(TypeError):
        Half()
