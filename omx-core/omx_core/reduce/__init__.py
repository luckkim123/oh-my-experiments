"""omx_core.reduce — Claude-free reduction verbs (summarize / series / plot / cache / promote / tb_final)."""
from omx_core.reduce.cache import read_cache, write_cache
from omx_core.reduce.plot import bar_plot, line_plot
from omx_core.reduce.promote import promote_plots
from omx_core.reduce.series import downsample, load_npz
from omx_core.reduce.summarize import add_cv, to_dataframe
from omx_core.reduce.tb_final import final_window_means

__all__ = [
    "to_dataframe", "add_cv",
    "load_npz", "downsample",
    "line_plot", "bar_plot",
    "write_cache", "read_cache",
    "promote_plots",
    "final_window_means",
]
