"""omx_core.tree_audit — the T1-T12 checks over the tree walker (R2 spec 2.3).

Report-only by design (lint family, INV-1): the verb never fixes anything;
--strict is the caller's opt-in escalation. F4 (same-second collision) is
deliberately absent — prevention lives in tree-scaffold's mint-time refusal."""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from omx_core.tree import (
    TreeSchema,
    parse_run_id,
    runs_at_declared_depth,
    walk_runs,
    walk_symlinks,
)


def _v(check, severity, path, message):
    return {"check": check, "severity": severity, "path": str(path),
            "message": message}


def _eval_leaf_ok(schema: TreeSchema, leaf: str) -> bool:
    parts = leaf.split("_")
    if len(parts) <= schema.ts_fields:
        return False
    ts = "_".join(parts[-schema.ts_fields:])
    mode = "_".join(parts[:-schema.ts_fields])
    return bool(schema.ts_pattern.fullmatch(ts)) and mode in schema.eval_modes


def audit_tree(schema: TreeSchema, base) -> dict:
    base = Path(base)
    entries = walk_runs(schema, base)
    v = []

    # T6 — run-shaped dir at an undeclared depth (any detection clause).
    for e in entries:
        if e["role"] == "index" and not e["at_declared_depth"]:
            v.append(_v("T6", "error", e["path"],
                        f"run-shaped dir at undeclared depth {e['depth']} "
                        f"(detected via {e['detected_via']})"))

    data_role = next((r for r in schema.trees.values() if r.name != "index"), None)
    data_root = (base / data_role.root) if data_role else None
    eval_base = schema.eval_pattern.split("/", 1)[0]
    pointer_targets = set()

    for e in runs_at_declared_depth(entries):
        run = e["path"]
        # T7 — grammar (incl. tag: required).
        if e["parsed"] is None:
            v.append(_v("T7", "error", run,
                        "leaf does not parse under the run_id grammar"))
        elif schema.tag == "required" and e["parsed"]["tag"] == "":
            v.append(_v("T7", "error", run, "tag missing (run_id.tag: required)"))
        # T8 — requires.
        for req in schema.requires:
            if not (run / req).exists():
                v.append(_v("T8", "warn", run / req, f"required file {req} missing"))
        # T1/T2/T3 — data pointers.
        for link in schema.data_pointers():
            lp = run / link.name
            if not os.path.lexists(lp):
                if link.required:
                    v.append(_v("T1", "error", lp,
                                f"required data_pointer {link.name!r} missing"))
                continue
            if lp.is_symlink() and not lp.exists():
                v.append(_v("T2", "error", lp, "data_pointer symlink dangling"))
                continue
            target = lp.resolve()
            pointer_targets.add(target)
            if data_root is not None:
                try:
                    target.relative_to(data_root.resolve())
                except ValueError:
                    v.append(_v("T3", "error", lp,
                                f"data_pointer target escapes {data_role.root}"))
        # T9 — undeclared entries (only when an allowlist is declared).
        if schema.entries is not None:
            allowed = (set(schema.entries) | set(schema.requires)
                       | {link.name for link in schema.links.values()} | {eval_base})
            for child in sorted(run.iterdir()):
                if child.name not in allowed and not child.name.startswith("."):
                    v.append(_v("T9", "warn", child,
                                f"undeclared run-dir entry {child.name!r}"))
        # T10 — deprecated patterns (error, carries the declared message).
        for child in sorted(run.iterdir()):
            for pat, msg in schema.deprecated:
                if fnmatch.fnmatch(child.name, pat):
                    v.append(_v("T10", "error", child, msg))
        # T11 — eval leaves.
        ev_dir = run / eval_base
        if ev_dir.is_dir():
            for child in sorted(ev_dir.iterdir()):
                if child.is_dir() and not _eval_leaf_ok(schema, child.name):
                    v.append(_v("T11", "warn", child,
                                "eval leaf does not match eval_pattern x eval_modes"))

    # T4/T5 — declared aliases.
    alias_specs = {link.name: link for link in schema.aliases()}
    for link in walk_symlinks(schema, base):
        spec = alias_specs.get(link["name"])
        if spec is None or link["role"] != "index":
            continue
        if link["target"] is None:
            v.append(_v("T4", "error", link["path"], "alias symlink dangling"))
            continue
        tgt = link["target"]
        if parse_run_id(schema, tgt.name) is None:
            v.append(_v("T5", "error", link["path"],
                        "alias target is not a grammar-valid run dir"))
        elif spec.scope != "root" and tgt.parent.resolve() != link["path"].parent.resolve():
            v.append(_v("T5", "error", link["path"],
                        f"alias target outside its {spec.scope!r} scope"))

    # T12 — mirror coherence (only when a data tree is declared).
    if data_role is not None:
        data_leaves = {e["path"].resolve() for e in entries if e["role"] == "data"}
        for d in sorted(data_leaves - pointer_targets):
            v.append(_v("T12", "warn", d,
                        "data run has no index counterpart (unindexed run)"))

    errors = sum(1 for i in v if i["severity"] == "error")
    return {"ok": errors == 0,
            "counts": {"error": errors, "warn": len(v) - errors},
            "violations": v}
