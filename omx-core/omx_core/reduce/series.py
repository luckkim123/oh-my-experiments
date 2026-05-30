"""omx_core.reduce.series — time-series loading + downsampling for plots.

Trajectories are (timesteps, n_envs); downsample thins axis 0 (time) by a
stride so a PNG curve carries <= max_points without distorting shape. Design 5:
keep plots small; a few thousand points is plenty for a vision-read curve.
"""
import math

import numpy as np


def load_npz(path) -> dict:
    """Load a .npz into a plain {name: ndarray} dict (materialized, file closed)."""
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


def downsample(arr: np.ndarray, max_points: int = 2000) -> np.ndarray:
    """Stride-thin along axis 0 so len(axis0) <= max_points. Keeps the first row.

    1-D and N-D supported (only axis 0 is thinned). No-op if already small.
    """
    if max_points <= 0:
        raise ValueError(f"max_points must be positive, got {max_points}")
    n = arr.shape[0]
    if n <= max_points:
        return arr
    stride = math.ceil(n / max_points)
    return arr[::stride]
