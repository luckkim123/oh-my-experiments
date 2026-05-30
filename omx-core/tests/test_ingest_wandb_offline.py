import numpy as np
import pytest
from omx_core.ingest import IngestAdapter, IngestResult
from omx_core.ingest.wandb_offline import WandbAdapter


def _wandb_fixture(fixtures_dir):
    return fixtures_dir / "wandb" / "run-synthetic.wandb"


def test_wandb_adapter_is_adapter():
    assert isinstance(WandbAdapter(), IngestAdapter)


def test_wandb_can_handle_local_log():
    assert WandbAdapter().can_handle("/x/run-abc.wandb") is True
    assert WandbAdapter().can_handle("wandb://run-abc") is True
    assert WandbAdapter().can_handle("/x/summary.json") is False


def test_wandb_ingest_offline_fills_series(fixtures_dir):
    res = WandbAdapter().ingest(_wandb_fixture(fixtures_dir))
    assert isinstance(res, IngestResult)
    assert "Reward/total" in res.series
    assert "Track/att/roll_err_deg" in res.series  # nested_key joined with '/'
    total = res.series["Reward/total"]
    assert isinstance(total, np.ndarray) and total.shape == (3,)
    assert np.isclose(total[0], -0.5) and np.isclose(total[-1], -0.3)
    assert res.meta["format"] == "wandb_offline"
    assert res.summary == []


def test_wandb_ingest_emits_step_companion(fixtures_dir):
    # Mirror the TB adapter contract: every series<key> has a _step/<key> x-axis
    # companion (from the record-level history step), so omx plot aligns wandb and
    # TB curves on the same logged-step axis instead of a 0..N fallback index.
    res = WandbAdapter().ingest(_wandb_fixture(fixtures_dir))
    for key in ("Reward/total", "Track/att/roll_err_deg"):
        step_key = f"_step/{key}"
        assert step_key in res.series, f"missing {step_key}"
        steps = res.series[step_key]
        assert isinstance(steps, np.ndarray) and steps.shape == (3,)
        assert np.array_equal(steps, np.array([0.0, 1.0, 2.0]))


def test_wandb_ingest_loud_fails_on_missing(tmp_path):
    from omx_core.omx_paths import OmxError
    with pytest.raises(OmxError):
        WandbAdapter().ingest(tmp_path / "run-nope.wandb")


def test_wandb_ingest_dir_resolution(fixtures_dir):
    res = WandbAdapter().ingest(f"wandb://{fixtures_dir / 'wandb'}")
    assert len(res.series) >= 2
