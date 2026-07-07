"""omx_core.wiki.sync — auto-synced reserved profile page (#17, spec 3.8).

profile.md is REGENERATED from .omx/profile/* (never hand-edited, never
append-merged) — a projection, not a page. It joins RESERVED_FILES so
write_page refuses it and list_pages hides it from index/lint/query; readers
use `omx wiki read --slug profile`. This kills the one-shot seed-page drift:
the projection follows the profile's mtime forever.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from omx_core.omx_paths import OmxPaths, atomic_path
from omx_core.seal import check_seal
from omx_core.wiki import storage
from omx_core.wiki.types import WikiError, WikiPage

_PROJECTED = ("metrics.yaml", "rules.md", "evaluator.sh", "launch.sh", "tree.yaml")


def _compose(paths: OmxPaths, now: str) -> WikiPage:
    metrics_fp = paths.profile_dir / "metrics.yaml"
    if not metrics_fp.exists():
        raise WikiError(f"no metrics.yaml at {paths.profile_dir}; run exp-init first")
    metrics = metrics_fp.read_text(encoding="utf-8")
    rules_fp = paths.profile_dir / "rules.md"
    rules = rules_fp.read_text(encoding="utf-8") if rules_fp.exists() else "(no rules.md)"
    seal = check_seal(paths)

    tree_fp = paths.tree_yaml()
    if tree_fp.exists():
        try:
            t = yaml.safe_load(tree_fp.read_text(encoding="utf-8")) or {}
            trees = t.get("trees") or {}
            roots = ", ".join(f"{k}: {(v or {}).get('root')}" for k, v in trees.items())
            levels = "; ".join(
                f"{k}: " + ("/".join(str(lv) for lv in ((v or {}).get('levels') or [])) or "(flat)")
                for k, v in trees.items())
            links = ", ".join((t.get("links") or {}).keys()) or "(none)"
            tree_summary = f"roots: {roots}\nlevels: {levels}\nlinks: {links}"
        except Exception:  # projection must never break the sync
            tree_summary = "(tree.yaml present but unparseable)"
    else:
        tree_summary = "(no tree.yaml)"

    content = (
        "\n# Workspace profile (auto-synced)\n\n"
        f"Regenerated from `.omx/profile/` at {now}. Do not edit; run "
        "`omx wiki sync-profile` after profile changes.\n\n"
        "## metrics.yaml\n\n```yaml\n" + metrics + "```\n\n"
        "## rules.md\n\n" + rules + "\n\n"
        "## tree schema\n\n" + tree_summary + "\n\n"
        f"## evaluator seal\n\nstatus: {seal['status']}"
        f" (sealed_at: {seal['sealed_at']})\n"
    )
    return WikiPage(slug="profile.md", title="Workspace profile (auto-synced)",
                    tags=["profile", "auto-synced"], created=now, updated=now,
                    category="environment", confidence="high", content=content)


def sync_profile_page(paths: OmxPaths, *, now: str) -> dict:
    present = [paths.profile_dir / n for n in _PROJECTED
               if (paths.profile_dir / n).exists()]
    if not present:
        raise WikiError(f"no profile at {paths.profile_dir}; run exp-init first")
    page_fp = paths.wiki_dir() / "profile.md"
    mtime_inputs = list(present)
    seal_fp = paths.seal_json()
    if seal_fp.exists():
        mtime_inputs.append(seal_fp)
    prof_mtime = max(f.stat().st_mtime for f in mtime_inputs)
    # STRICT >: a same-second tie re-syncs (idempotent) instead of being missed
    if page_fp.exists() and page_fp.stat().st_mtime > prof_mtime:
        return {"action": "unchanged", "slug": "profile.md"}

    def _do() -> dict:
        with atomic_path(page_fp) as tmp:
            Path(tmp).write_text(storage.serialize_page(_compose(paths, now)),
                                 encoding="utf-8")
        storage.append_log(paths, now=now, operation="sync-profile",
                           pages=["profile.md"], summary="regenerated from .omx/profile/")
        return {"action": "synced", "slug": "profile.md"}

    return storage.with_wiki_lock(paths, _do)
