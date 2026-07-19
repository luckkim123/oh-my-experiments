"""omx_core.reduce.plot — headless PNG generation (matplotlib Agg backend).

CRITICAL: set the Agg backend BEFORE importing pyplot — this container is
headless (no display). Design 5: cap width so a vision-read PNG stays small.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")          # MUST precede pyplot import (headless Docker)
import matplotlib.pyplot as plt  # noqa: E402

_DPI = 100


def _save(fig, out_path, max_px):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # cap figure width: width_in * dpi <= max_px
    max_in = max_px / _DPI
    w_in, h_in = fig.get_size_inches()
    if w_in > max_in:
        fig.set_size_inches(max_in, h_in * (max_in / w_in))
    fig.savefig(out_path, dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    return out_path


def line_plot(x, series: dict, out_path, *, title=None, max_px=2576) -> Path:
    """Overlay named 1-D series against x. series = {label: ndarray}."""
    fig, ax = plt.subplots()
    for label, y in series.items():
        ax.plot(x, y, label=label, linewidth=1.0)
    if title:
        ax.set_title(title)
    ax.legend(loc="best", fontsize="small")
    ax.grid(True, alpha=0.3)
    return _save(fig, out_path, max_px)


def bar_plot(labels, values, out_path, *, title=None, max_px=2576) -> Path:
    """Simple categorical bar chart (e.g. ss_error per axis)."""
    fig, ax = plt.subplots()
    ax.bar(range(len(labels)), values)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    if title:
        ax.set_title(title)
    ax.grid(True, axis="y", alpha=0.3)
    return _save(fig, out_path, max_px)
