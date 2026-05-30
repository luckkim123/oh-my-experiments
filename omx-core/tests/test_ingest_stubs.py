import pytest
from omx_core.ingest import IngestAdapter
from omx_core.ingest.stubs import WandbAdapter, TensorboardAdapter


def test_stubs_are_adapters():
    assert isinstance(WandbAdapter(), IngestAdapter)
    assert isinstance(TensorboardAdapter(), IngestAdapter)


def test_wandb_can_handle_by_scheme():
    assert WandbAdapter().can_handle("wandb://entity/project/run") is True
    assert WandbAdapter().can_handle("/local/summary.json") is False


def test_tb_can_handle_by_event_filename():
    assert TensorboardAdapter().can_handle("/x/events.out.tfevents.123") is True
    assert TensorboardAdapter().can_handle("/x/summary.json") is False


def test_ingest_raises_not_implemented_with_build_pointer():
    with pytest.raises(NotImplementedError, match="build #4"):
        WandbAdapter().ingest("wandb://e/p/r")
    with pytest.raises(NotImplementedError, match="build #4"):
        TensorboardAdapter().ingest("/x/events.out.tfevents.1")
