"""Regenerate the workspace-profile projection in hq's work layer."""
from __future__ import annotations

from pathlib import Path

import yaml

from omx_core.omx_paths import OmxError, OmxPaths, atomic_path
from omx_core.seal import check_seal

_PROJECTED = ("metrics.yaml", "rules.md", "evaluator.sh", "launch.sh", "tree.yaml")


def _compose(paths: OmxPaths, now: str) -> str:
    metrics_fp = paths.profile_dir / "metrics.yaml"
    if not metrics_fp.exists():
        raise OmxError(f"no metrics.yaml at {paths.profile_dir}; run exp-init first")
    metrics = metrics_fp.read_text(encoding="utf-8")
    rules_fp = paths.profile_dir / "rules.md"
    rules = rules_fp.read_text(encoding="utf-8") if rules_fp.exists() else "(no rules.md)"
    seal = check_seal(paths)
    tree_fp = paths.tree_yaml()
    if tree_fp.exists():
        try:
            tree = yaml.safe_load(tree_fp.read_text(encoding="utf-8")) or {}
            trees = tree.get("trees") or {}
            roots = ", ".join(f"{key}: {(value or {}).get('root')}"
                              for key, value in trees.items())
            levels = "; ".join(
                f"{key}: " + ("/".join(str(level) for level in ((value or {}).get("levels") or []))
                               or "(flat)") for key, value in trees.items())
            links = ", ".join((tree.get("links") or {}).keys()) or "(none)"
            tree_summary = f"roots: {roots}\nlevels: {levels}\nlinks: {links}"
        except Exception:
            tree_summary = "(tree.yaml present but unparseable)"
    else:
        tree_summary = "(no tree.yaml)"
    return (
        "\n# Workspace profile (auto-synced)\n\n"
        f"Regenerated from `.omx/profile/` at {now}. Do not edit; run "
        "`omx wiki sync-profile` after profile changes.\n\n"
        "## metrics.yaml\n\n```yaml\n" + metrics + "```\n\n"
        "## rules.md\n\n" + rules + "\n\n"
        "## tree schema\n\n" + tree_summary + "\n\n"
        f"## evaluator seal\n\nstatus: {seal['status']}"
        f" (sealed_at: {seal['sealed_at']})\n")


def sync_profile_page(paths: OmxPaths, *, now: str) -> dict:
    """Write the regenerable profile outside community posts (store-spec §3)."""
    present = [paths.profile_dir / name for name in _PROJECTED
               if (paths.profile_dir / name).exists()]
    if not present:
        raise OmxError(f"no profile at {paths.profile_dir}; run exp-init first")
    page_fp = paths.profile_projection()
    inputs = list(present)
    seal_fp = paths.seal_json()
    if seal_fp.exists():
        inputs.append(seal_fp)
    if page_fp.exists() and page_fp.stat().st_mtime > max(path.stat().st_mtime for path in inputs):
        return {"action": "unchanged", "path": str(page_fp)}
    with atomic_path(page_fp) as tmp:
        Path(tmp).write_text(_compose(paths, now), encoding="utf-8")
    return {"action": "synced", "path": str(page_fp)}
