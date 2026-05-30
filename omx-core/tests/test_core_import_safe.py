import subprocess
import sys


def test_core_imports_without_eager_heavy_deps():
    # importing the package + cli must NOT import wandb/tensorboard at module load
    code = (
        "import omx_core, omx_core.cli, omx_core.ingest.tensorboard, "
        "omx_core.ingest.wandb_offline, sys; "
        "assert 'wandb' not in sys.modules, 'wandb imported eagerly'; "
        "assert 'tensorboard' not in sys.modules, 'tensorboard imported eagerly'; "
        "print('OK')"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "OK" in r.stdout
