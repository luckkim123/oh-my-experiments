from omx_core.ingest import IngestAdapter
from omx_core.ingest.tensorboard import TensorboardAdapter
from omx_core.ingest.wandb_offline import WandbAdapter


def test_real_adapters_are_adapters():
    assert isinstance(WandbAdapter(), IngestAdapter)
    assert isinstance(TensorboardAdapter(), IngestAdapter)


def test_can_handle_routing():
    assert WandbAdapter().can_handle("wandb://run") is True
    assert WandbAdapter().can_handle("/x/run-a.wandb") is True
    assert TensorboardAdapter().can_handle("/x/events.out.tfevents.1") is True
    assert TensorboardAdapter().can_handle("/x/summary.json") is False
