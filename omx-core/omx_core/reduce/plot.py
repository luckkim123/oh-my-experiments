"""omx_core.reduce.plot — headless figure generation (matplotlib Agg backend).

CRITICAL: set the Agg backend BEFORE importing pyplot — this container is
headless (no display). Design 5: cap width so a vision-read PNG stays small.

Two audiences, one renderer. The DEFAULTS render a *triage* figure — 100 dpi,
in-figure title, no axis labels — sized for an agent to read with vision, which
is what Design 5 is about. A **paper** figure needs the opposite: 300-600 dpi,
labelled axes, no in-figure title (the caption carries it), and vector output.
Each of those is an opt-in keyword, so a caller that passes none of them gets
byte-identical behaviour to before.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")          # MUST precede pyplot import (headless Docker)
import matplotlib.pyplot as plt  # noqa: E402

_DPI = 100


def _save(fig, out_path, max_px, dpi=_DPI):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Cap figure WIDTH. max_px is quoted at the reference dpi (_DPI), not at the
    # requested one — otherwise raising dpi for a paper figure would shrink the
    # figure in inches and hand back the same pixel count, defeating the flag.
    # At dpi=_DPI this is the original `max_px / _DPI` and nothing moves.
    max_in = max_px / _DPI
    w_in, h_in = fig.get_size_inches()
    if w_in > max_in:
        fig.set_size_inches(max_in, h_in * (max_in / w_in))
    # Format follows out_path's suffix: .png raster, .pdf/.svg vector (dpi then
    # only affects embedded rasters, which is correct).
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out_path


def line_plot(x, series: dict, out_path, *, title=None, max_px=2576,
              dpi=_DPI, xlabel=None, ylabel=None) -> Path:
    """Overlay named 1-D series against x. series = {label: ndarray}."""
    fig, ax = plt.subplots()
    for label, y in series.items():
        ax.plot(x, y, label=label, linewidth=1.0)
    if title:
        ax.set_title(title)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.legend(loc="best", fontsize="small")
    ax.grid(True, alpha=0.3)
    return _save(fig, out_path, max_px, dpi=dpi)


def bar_plot(labels, values, out_path, *, title=None, max_px=2576,
             dpi=_DPI, xlabel=None, ylabel=None) -> Path:
    """Simple categorical bar chart (e.g. ss_error per axis)."""
    fig, ax = plt.subplots()
    ax.bar(range(len(labels)), values)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    if title:
        ax.set_title(title)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.grid(True, axis="y", alpha=0.3)
    return _save(fig, out_path, max_px, dpi=dpi)
