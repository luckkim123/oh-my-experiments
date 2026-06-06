"""omx_core.reduce — Claude-free reduction verbs (summarize / series / plot / cache / promote / tb_final)."""
from omx_core.reduce.summarize import to_dataframe, add_cv
from omx_core.reduce.series import load_npz, downsample
from omx_core.reduce.plot import line_plot, bar_plot
from omx_core.reduce.cache import write_cache, read_cache
from omx_core.reduce.promote import promote_plots
from omx_core.reduce.tb_final import final_window_means

__all__ = [
    "to_dataframe", "add_cv",
    "load_npz", "downsample",
    "line_plot", "bar_plot",
    "write_cache", "read_cache",
    "promote_plots",
    "final_window_means",
]
