"""omx_core.reduce.cache — re-derivable derived-data cache in .omx/runs/<id>/cache/.

Numpy .npz (pyarrow absent; design 10.2 'parquet' was an example, the principle
is a re-derivable cache). Path comes ONLY from omx_paths.cache_path; atomic via
atomic_path. read_cache returns None on miss (caller re-derives).
"""
import numpy as np

from omx_core.omx_paths import OmxPaths, atomic_path


def write_cache(paths: OmxPaths, run_id, *, source, metric, arrays: dict):
    """Atomically np.savez `arrays` to the canonical cache path. Returns the path."""
    target = paths.cache_path(run_id, source=source, metric=metric)
    target.parent.mkdir(parents=True, exist_ok=True)
    with atomic_path(target) as tmp:
        # np.savez appends .npz to a path arg whose name lacks it, which would
        # break the atomic rename. Pass a file object so the bytes go to `tmp` verbatim.
        with open(tmp, "wb") as fh:
            np.savez(fh, **arrays)
    return target


def read_cache(paths: OmxPaths, run_id, *, source, metric):
    """Return {name: ndarray} if the cache exists, else None (caller re-derives)."""
    target = paths.cache_path(run_id, source=source, metric=metric)
    if not target.exists():
        return None
    with np.load(target) as z:
        return {k: z[k] for k in z.files}
