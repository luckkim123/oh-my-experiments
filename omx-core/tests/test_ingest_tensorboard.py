import numpy as np
import pytest
from omx_core.ingest import IngestAdapter, IngestResult
from omx_core.ingest.tensorboard import TensorboardAdapter


def _tb_fixture(fixtures_dir):
    return fixtures_dir / "tb" / "events.out.tfevents.synthetic"


def test_tb_adapter_is_adapter():
    assert isinstance(TensorboardAdapter(), IngestAdapter)


def test_tb_can_handle_event_filename():
    assert TensorboardAdapter().can_handle("/x/events.out.tfevents.123") is True
    assert TensorboardAdapter().can_handle("/x/summary.json") is False


def test_tb_ingest_fills_series_with_real_scalars(fixtures_dir):
    res = TensorboardAdapter().ingest(_tb_fixture(fixtures_dir))
    assert isinstance(res, IngestResult)
    assert "Reward/total" in res.series
    assert "Track/att/roll_err_deg" in res.series
    roll = res.series["Track/att/roll_err_deg"]
    assert isinstance(roll, np.ndarray) and roll.shape == (5,)
    assert np.isclose(roll[0], 20.0) and np.isclose(roll[-1], 12.0)
    assert "_step/Track/att/roll_err_deg" in res.series
    assert res.series["_step/Track/att/roll_err_deg"].tolist() == [0, 1, 2, 3, 4]
    assert res.meta["format"] == "tensorboard"
    assert res.summary == []


def test_tb_ingest_loud_fails_on_missing_file(tmp_path):
    from omx_core.omx_paths import OmxError
    with pytest.raises((OmxError, FileNotFoundError, ValueError)):
        TensorboardAdapter().ingest(tmp_path / "events.out.tfevents.nope")
