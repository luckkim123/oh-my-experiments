"""omx_core.tree_ops — codify / scaffold / alias / index operations (R2).

Everything here is generated FROM the TreeSchema (approach A): scaffold and
alias never invent structure the schema does not declare, and codify only
reports what the census actually observed (pending_approval + per-field
matched/sampled evidence)."""
from __future__ import annotations

import fnmatch
import json
import os
from collections import Counter
from pathlib import Path

from omx_core.tree import (
    TreeError,
    TreeSchema,
    compile_ts_pattern,
    parse_run_id,
    runs_at_declared_depth,
    walk_runs,
    walk_symlinks,
)

_TS_CANDIDATES = ("%y%m%d_%H%M%S", "%Y%m%d_%H%M%S", "%Y-%m-%d_%H-%M-%S")
_DEFAULT_IGNORE = ("legacy", "_*")
_MAX_SCAN_DEPTH = 6


def _skip_name(name: str) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in _DEFAULT_IGNORE)


def _iter_dirs(root: Path, max_depth: int):
    """(dir, depth) below root; symlinks and default-ignored segments skipped."""
    def _scan(d: Path, depth: int):
        for child in sorted(d.iterdir()):
            if not child.is_dir() or child.is_symlink() or _skip_name(child.name):
                continue
            yield child, depth
            if depth < max_depth:
                yield from _scan(child, depth + 1)
    yield from _scan(root, 1)


def codify_tree(base, *, index_root=None, data_root=None) -> tuple:
    base = Path(base)
    if index_root:
        iroot = base / index_root
        if not iroot.is_dir():
            raise TreeError(f"index root {index_root!r} not found under {base}")
    else:
        iroot = base / "experiments"
        if not iroot.is_dir():
            raise TreeError(
                f"no experiments/ under {base}; pass --index-root <relpath>")

    # 1. Run candidates: manifest.json OR a symlink entry escaping the index tree.
    runs = []
    for d, depth in _iter_dirs(iroot, _MAX_SCAN_DEPTH):
        has_manifest = (d / "manifest.json").is_file()
        pointers = []
        for child in sorted(d.iterdir()):
            if child.is_symlink() and child.exists():
                tgt = child.resolve()
                try:
                    tgt.relative_to(iroot.resolve())
                except ValueError:
                    pointers.append((child.name, tgt))
        if has_manifest or pointers:
            runs.append({"path": d, "leaf": d.name, "depth": depth,
                         "manifest": has_manifest, "pointers": pointers})
    if not runs:
        raise TreeError(
            "no runs detected under the index root — codify is census-based and "
            "refuses to guess from an empty tree; `omx init` writes the generic default")
    sampled = len(runs)
    report = {}

    # 2. Levels from the depth census (run depth = levels + 1); names are
    # placeholders (level1..levelN) — cosmetic, renamed at human approval.
    depths = sorted({r["depth"] for r in runs})
    min_l, max_l = depths[0] - 1, depths[-1] - 1
    levels = [f"level{i}" + ("?" if i > min_l else "") for i in range(1, max_l + 1)]
    report["levels"] = {"value": levels, "matched": sampled, "sampled": sampled}

    # 3. ts_format: best candidate over run-leaf tails.
    best = None
    for fmt in _TS_CANDIDATES:
        pat, nf = compile_ts_pattern(fmt)
        hits = sum(1 for r in runs
                   if len(r["leaf"].split("_")) > nf
                   and pat.fullmatch("_".join(r["leaf"].split("_")[-nf:])))
        if best is None or hits > best[1]:
            best = (fmt, hits, nf, pat)
    ts_format, ts_hits, nf, pat = best
    report["ts_format"] = {"value": ts_format, "matched": ts_hits, "sampled": sampled}

    # 4. Tag census under the dash-only-label split (>=90% -> required).
    parseable = tagged = 0
    for r in runs:
        parts = r["leaf"].split("_")
        if len(parts) > nf and pat.fullmatch("_".join(parts[-nf:])):
            parseable += 1
            if len(parts) > nf + 1:
                tagged += 1
    tag = "required" if parseable and tagged / parseable >= 0.9 else "optional"
    report["tag"] = {"value": tag, "matched": tagged, "sampled": parseable}

    # 5. Data pointers: symlink-name census (>=50% presence; required at >=90%).
    pointer_names = Counter(n for r in runs for n, _ in r["pointers"])
    link_lines = []
    pointer_targets = []
    for name, count in sorted(pointer_names.items()):
        if count / sampled >= 0.5:
            req = "true" if count / sampled >= 0.9 else "false"
            link_lines.append(f"  {name}: {{kind: data_pointer, required: {req}}}")
            pointer_targets += [t for r in runs for n, t in r["pointers"] if n == name]
    report["data_pointers"] = {"value": sorted(n for n, c in pointer_names.items()
                                               if c / sampled >= 0.5),
                               "matched": sum(pointer_names.values()),
                               "sampled": sampled}

    # 6. Alias census: symlinks at level dirs targeting a run candidate.
    run_paths = {r["path"].resolve() for r in runs}
    aliases = {}
    level_dirs = [(iroot, 0)] + [(d, dep) for d, dep in _iter_dirs(iroot, max_l)]
    for d, depth in level_dirs:
        for child in sorted(d.iterdir()):
            if child.is_symlink() and child.exists() and child.resolve() in run_paths:
                aliases.setdefault(child.name,
                                   "root" if depth == 0 else f"level{depth}")
    for name, scope in sorted(aliases.items()):
        link_lines.append(f"  {name}: {{kind: alias, scope: {scope}}}")
    report["aliases"] = {"value": sorted(aliases), "matched": len(aliases),
                         "sampled": sampled}

    # 7. Data root: hint, else common ancestor of the pointer targets' parents.
    # Single-branch caveat recorded in the report: with one observed exp dir the
    # common ancestor may sit one level too deep (human corrects at approval).
    droot_rel = None
    if data_root:
        droot_rel = str(data_root)
    elif pointer_targets:
        common = Path(os.path.commonpath([str(t.parent) for t in pointer_targets]))
        try:
            droot_rel = str(common.resolve().relative_to(base.resolve()))
        except ValueError:
            droot_rel = str(common)
    report["data_root"] = {"value": droot_rel,
                           "matched": len(pointer_targets), "sampled": sampled,
                           "note": "common-ancestor inference; may sit deeper than "
                                   "the true root when only one branch was observed"}

    # 8. Eval modes + requires.
    modes = set()
    for r in runs:
        ev = r["path"] / "eval"
        if ev.is_dir():
            for child in sorted(ev.iterdir()):
                parts = child.name.split("_")
                if len(parts) > nf and pat.fullmatch("_".join(parts[-nf:])):
                    mode = "_".join(parts[:-nf])
                    if mode:
                        modes.add(mode)
    eval_modes = sorted(modes) or ["static"]
    report["eval_modes"] = {"value": eval_modes, "matched": len(modes),
                            "sampled": sampled}
    man = sum(1 for r in runs if r["manifest"])
    requires = ["manifest.json"] if man / sampled >= 0.5 else []
    report["requires"] = {"value": requires, "matched": man, "sampled": sampled}

    # 9. Compose the instance (deterministic ordering; loader-valid by construction).
    def _yaml_list(items):
        return "[" + ", ".join(json.dumps(i) if i.endswith("?") else i
                               for i in items) + "]"

    lines = [
        "# omx tree schema — codified from the existing tree by `omx tree-codify`.",
        "# Review before approval: level NAMES are placeholders (level1..levelN);",
        "# rename them, and add run_dir.entries / deprecated as this project needs.",
        "# v1 limitation: run_id labels are dash-only ([a-z0-9-]); a writer that",
        "# emits underscore-bearing labels gets the label tail attributed to the",
        "# tag (affects only tag-presence checks, never a crash).",
        "version: 1",
        "pending_approval: true",
        "trees:",
        "  index:",
        f"    root: {iroot.relative_to(base)}",
        f"    levels: {_yaml_list(levels)}" if levels else "    levels: []",
    ]
    if droot_rel:
        lines += ["  data:", f"    root: {droot_rel}", "    levels: []"]
    lines += [
        "run_id:",
        f"  grammar: \"<label>[_<tag>]_<ts>\"",
        f"  ts_format: \"{ts_format}\"",
        f"  tag: {tag}",
    ]
    if link_lines:
        lines += ["links:"] + link_lines
    lines += ["run_dir:"]
    lines += [f"  requires: [{', '.join(requires)}]" if requires else "  requires: []"]
    lines += [
        "  eval_pattern: \"eval/<mode>_<ts>\"",
        f"  eval_modes: [{', '.join(eval_modes)}]",
        "walk:",
        "  ignore: [\"legacy\", \"_*\"]",
        "",
    ]
    return "\n".join(lines), report


# --- scaffold / shared run resolution (spec 2.4) ------------------------------

def resolve_run_dir(schema: TreeSchema, base, spec) -> Path:
    """Resolve a run spec: an existing dir path, else an EXACT leaf name among
    detected runs. Deterministic — no substring convenience (that is a
    workspace resolver's affordance, not core's)."""
    p = Path(spec)
    if p.is_dir():
        return p
    hits = [e["path"] for e in runs_at_declared_depth(walk_runs(schema, base))
            if e["leaf"] == str(spec)]
    if not hits:
        raise TreeError(f"no run named {spec!r} in the index tree")
    if len(hits) > 1:
        raise TreeError(f"run name {spec!r} is ambiguous: "
                        f"{[str(h) for h in hits]}; pass a path")
    return hits[0]


def scaffold_run(schema: TreeSchema, base, run_id, *, under="", data_dir=None) -> Path:
    parsed = parse_run_id(schema, run_id)
    if parsed is None:
        raise TreeError(f"run_id {run_id!r} does not parse under the grammar "
                        f"(<label>[_<tag>]_<ts>, ts_format {schema.ts_format!r})")
    if schema.tag == "required" and parsed["tag"] == "":
        raise TreeError(f"run_id {run_id!r} has no tag (run_id.tag: required) — "
                        "F8 refused at mint time")
    role = schema.trees["index"]
    segs = [s for s in str(under).split("/") if s]
    if not role.min_levels <= len(segs) <= role.max_levels:
        raise TreeError(f"--under {under!r} has {len(segs)} segment(s); the index "
                        f"tree declares {role.min_levels}..{role.max_levels} level(s)")
    run_dir = Path(base) / role.root
    for s in segs:
        run_dir = run_dir / s
    run_dir = run_dir / run_id
    if run_dir.exists():
        raise TreeError(f"{run_dir} already exists — scaffold refuses to reuse a "
                        "leaf (F4 same-second guard); mint a fresh ts")
    run_dir.mkdir(parents=True)
    for e in (schema.entries or ()):
        (run_dir / e).mkdir()
    if data_dir is not None:
        for link in schema.data_pointers():
            (run_dir / link.name).symlink_to(
                os.path.relpath(Path(data_dir).resolve(), run_dir))
    return run_dir


def scaffold_eval(schema: TreeSchema, base, run_spec, mode, *, now_ts) -> Path:
    # mode FIRST (cheap vocabulary check, its own error), then run resolution.
    if mode not in schema.eval_modes:
        raise TreeError(f"mode {mode!r} not in eval_modes {list(schema.eval_modes)}")
    run_dir = resolve_run_dir(schema, base, run_spec)
    leaf = schema.eval_pattern.replace("<mode>", mode).replace("<ts>", now_ts)
    target = run_dir / leaf
    if target.exists():
        raise TreeError(f"{target} already exists (F4 same-second guard)")
    target.mkdir(parents=True)
    return target


# --- alias (spec 2.5) ---------------------------------------------------------

def set_alias(schema: TreeSchema, base, name, run_spec, *, scope_path=None) -> dict:
    link = schema.links.get(name)
    if link is None or link.kind != "alias":
        raise TreeError(f"{name!r} is not a declared alias in tree.yaml links "
                        "(undeclared aliases are exactly the drift tree-audit flags)")
    run_dir = resolve_run_dir(schema, base, run_spec)
    if parse_run_id(schema, run_dir.name) is None:
        raise TreeError(f"alias target {run_dir.name!r} is not a grammar-valid run dir")
    role = schema.trees["index"]
    index_root = Path(base) / role.root
    if scope_path is not None:
        scope_dir = Path(scope_path)
        if not scope_dir.is_dir():
            raise TreeError(f"--scope-path {scope_path!r} is not a directory")
    elif link.scope == "root":
        scope_dir = index_root
    else:
        # Derive from the target run's own ancestry (spec 2.5): the run's
        # enclosing dir at the alias's declared level position.
        pos = [n for n, _ in role.levels].index(link.scope) + 1
        rel = run_dir.resolve().relative_to(index_root.resolve())
        used_levels = len(rel.parts) - 1
        if used_levels < pos:
            raise TreeError(f"run {run_dir.name!r} omits the optional "
                            f"{link.scope!r} level; pass --scope-path explicitly")
        scope_dir = index_root.joinpath(*rel.parts[:pos])
    try:
        run_dir.resolve().relative_to(scope_dir.resolve())
    except ValueError:
        raise TreeError(f"alias target {run_dir} is outside the {link.scope!r} "
                        f"scope {scope_dir} — refusing a cross-scope alias")
    alias_fp = scope_dir / name
    if alias_fp.exists() and not alias_fp.is_symlink():
        raise TreeError(f"{alias_fp} exists and is not a symlink — refusing to replace")
    tmp = scope_dir / f".{name}.tmp{os.getpid()}"
    if os.path.lexists(tmp):
        tmp.unlink()
    tmp.symlink_to(os.path.relpath(run_dir.resolve(), scope_dir.resolve()))
    os.replace(tmp, alias_fp)
    return {"name": name, "scope_dir": str(scope_dir), "target": str(run_dir)}


def list_aliases(schema: TreeSchema, base) -> list:
    names = {l.name for l in schema.aliases()}
    out = []
    for l in walk_symlinks(schema, base):
        if l["name"] in names:
            out.append({"name": l["name"], "path": str(l["path"]),
                        "target": str(l["target"]) if l["target"] else None,
                        "dangling": l["target"] is None})
    return out
