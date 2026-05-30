"""omx_core.reduce.promote — B3 plot promotion (scratch -> permanent).

exp-analyze writes ALL candidate PNGs to scratch/<sid>/plots/; only those the
final report.md references are promoted into the permanent analysis/<aid>/plots/
tree (atomic os.replace). Unreferenced candidates stay in scratch for omx clean.
This is the single rule that keeps the permanent output tree clean (design B3/10.1).
"""
import os
from pathlib import Path

from omx_core.omx_paths import OmxError


def promote_plots(scratch_plots_dir, dest_plots_dir, referenced) -> list:
    """Move each referenced PNG from scratch_plots_dir to dest_plots_dir.

    referenced = list of bare filenames (e.g. 'ss_error__trajectory.png') that the
    report.md cites. Loud-fails (before moving anything) if a referenced file is
    absent in scratch -- a report citing a plot that was never rendered is a bug, not
    a silent skip. Returns the list of destination Paths. Unreferenced scratch files
    are left untouched.
    """
    scratch = Path(scratch_plots_dir)
    dest = Path(dest_plots_dir)
    # Pre-flight: verify every referenced file exists BEFORE any move (no partial promotion).
    missing = [name for name in referenced if not (scratch / name).exists()]
    if missing:
        raise OmxError(
            f"report references plot(s) not found in scratch {scratch}: {missing}")
    if not referenced:
        return []
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    for name in referenced:
        target = dest / name
        os.replace(scratch / name, target)  # atomic within a filesystem
        moved.append(target)
    return moved
