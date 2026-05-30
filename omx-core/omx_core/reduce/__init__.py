"""omx_core.reduce — Claude-free reduction verbs (summarize / series / plot / cache)."""
from omx_core.reduce.summarize import to_dataframe, add_cv
from omx_core.reduce.series import load_npz, downsample
from omx_core.reduce.plot import line_plot, bar_plot
from omx_core.reduce.cache import write_cache, read_cache

__all__ = [
    "to_dataframe", "add_cv",
    "load_npz", "downsample",
    "line_plot", "bar_plot",
    "write_cache", "read_cache",
]
