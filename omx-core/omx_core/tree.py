"""omx_core.tree — declarative experiment-tree schema (R2, design D10).

`.omx/profile/tree.yaml` declares THIS project's experiment output-tree
conventions (roots, hierarchy levels, run_id grammar, links, eval layout).
Core knows only the section TYPES; every value lives in the per-project
instance (D12). All four tree verbs derive from this one model: audit =
validate, scaffold = generate, alias = the links section, index = walk.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from omx_core.omx_paths import OmxError


class TreeError(OmxError):
    """Loud-fail for any tree.yaml schema or tree-verb error."""


GRAMMAR_V1 = "<label>[_<tag>]_<ts>"
_TS_TOKENS = {"%Y": 4, "%y": 2, "%m": 2, "%d": 2, "%H": 2, "%M": 2, "%S": 2}
_LEVEL_NAME = re.compile(r"\A[a-z][a-z0-9_]*\Z")
_LABEL = re.compile(r"\A[a-z0-9][a-z0-9-]*\Z")
_TAG = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_MODE = re.compile(r"\A[a-z0-9][a-z0-9_]*\Z")

_TOP_KEYS = frozenset({"version", "trees", "run_id", "links", "run_dir", "walk",
                       "pending_approval"})
_TREE_KEYS = frozenset({"root", "levels"})
_RUN_ID_KEYS = frozenset({"grammar", "ts_format", "tag"})
_LINK_KEYS = frozenset({"kind", "scope", "required"})
_RUN_DIR_KEYS = frozenset({"requires", "entries", "eval_pattern", "eval_modes",
                           "deprecated"})
_WALK_KEYS = frozenset({"ignore"})


def compile_ts_pattern(ts_format: str) -> tuple[re.Pattern, int]:
    """Translate a strftime format into an anchored digit regex.

    Only digit-producing tokens are allowed; '_' is the field separator the
    run_id split relies on; '-' is tolerated as an in-field literal (legacy
    long formats). Returns (pattern, n_fields) where n_fields is the number
    of '_'-separated fields the timestamp occupies in a leaf name.
    """
    out = []
    i = 0
    while i < len(ts_format):
        ch = ts_format[i]
        if ch == "%":
            tok = ts_format[i:i + 2]
            if tok not in _TS_TOKENS:
                raise TreeError(
                    f"ts_format token {tok!r} unsupported (digit-producing tokens only)")
            out.append(r"\d{%d}" % _TS_TOKENS[tok])
            i += 2
        elif ch == "_":
            out.append("_")
            i += 1
        elif ch == "-":
            out.append("-")
            i += 1
        else:
            raise TreeError(
                f"ts_format literal {ch!r} unsupported (tokens, '_' and '-' only)")
    return re.compile(r"\A" + "".join(out) + r"\Z"), ts_format.count("_") + 1


@dataclass(frozen=True)
class TreeRole:
    name: str
    root: str
    levels: tuple  # of (level_name, optional: bool)

    @property
    def min_levels(self) -> int:
        return sum(1 for _, opt in self.levels if not opt)

    @property
    def max_levels(self) -> int:
        return len(self.levels)


@dataclass(frozen=True)
class LinkSpec:
    name: str
    kind: str            # "data_pointer" | "alias"
    scope: str           # alias: "root" | declared index level name; data_pointer: "run"
    required: bool


@dataclass(frozen=True)
class TreeSchema:
    version: int
    trees: dict
    ts_format: str
    ts_pattern: re.Pattern
    ts_fields: int
    tag: str             # "required" | "optional"
    links: dict
    requires: tuple
    entries: tuple | None
    eval_pattern: str
    eval_modes: tuple
    deprecated: tuple    # of (pattern, message)
    ignore: tuple

    def data_pointers(self) -> list:
        return [link for link in self.links.values() if link.kind == "data_pointer"]

    def aliases(self) -> list:
        return [link for link in self.links.values() if link.kind == "alias"]


def _require_keys(section: str, data: dict, allowed: frozenset) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise TreeError(f"tree.yaml {section}: unknown keys {sorted(unknown)} (typo guard)")


def parse_run_id(schema: TreeSchema, leaf: str) -> dict | None:
    """Split a run-dir leaf into {label, tag, ts} under grammar v1, else None.

    Deterministic under the dash-only-label assumption (spec 2.1): the
    trailing ts fields are peeled first, the first remaining field is the
    label, the middle (possibly '_'-joined) is the tag. Never raises — an
    unparseable leaf is simply not run-shaped.
    """
    parts = leaf.split("_")
    if len(parts) < schema.ts_fields + 1:
        return None
    ts = "_".join(parts[-schema.ts_fields:])
    if not schema.ts_pattern.fullmatch(ts):
        return None
    label = parts[0]
    if not _LABEL.fullmatch(label):
        return None
    tag = "_".join(parts[1:-schema.ts_fields])
    if tag and not _TAG.fullmatch(tag):
        return None
    return {"label": label, "tag": tag, "ts": ts}


def segment_ignored(schema: TreeSchema, name: str) -> bool:
    """True when a path segment matches any walk.ignore pattern (fnmatch)."""
    return any(fnmatch.fnmatch(name, pat) for pat in schema.ignore)


def load_tree_schema(path) -> TreeSchema:
    fp = Path(path)
    if not fp.exists():
        raise TreeError(
            f"no tree.yaml at {fp}; run `omx init` (writes the generic default) "
            "or `omx tree-codify` (infers it from an existing tree)")
    data = yaml.safe_load(fp.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TreeError("tree.yaml must parse to a mapping")
    _require_keys("top level", data, _TOP_KEYS)
    if data.get("version") != 1:
        raise TreeError(f"tree.yaml version must be 1, got {data.get('version')!r}")

    trees_raw = data.get("trees")
    if not isinstance(trees_raw, dict) or "index" not in trees_raw:
        raise TreeError("trees must be a mapping containing the required 'index' role")
    trees = {}
    for role, spec in trees_raw.items():
        if not isinstance(spec, dict):
            raise TreeError(f"trees.{role} must be a mapping")
        _require_keys(f"trees.{role}", spec, _TREE_KEYS)
        root = spec.get("root")
        if not isinstance(root, str) or root == "":
            raise TreeError(f"trees.{role}.root must be a non-empty string")
        levels = []
        seen_opt = False
        for lv in spec.get("levels") or []:
            if not isinstance(lv, str):
                raise TreeError(f"trees.{role}.levels entries must be strings")
            opt = lv.endswith("?")
            name = lv[:-1] if opt else lv
            if not _LEVEL_NAME.fullmatch(name):
                raise TreeError(f"trees.{role} level name {name!r} invalid "
                                "(lowercase [a-z][a-z0-9_]*)")
            if seen_opt and not opt:
                raise TreeError(f"trees.{role}: required level {name!r} may not follow "
                                "an optional level (depth would be ambiguous)")
            seen_opt = seen_opt or opt
            levels.append((name, opt))
        trees[role] = TreeRole(name=role, root=root, levels=tuple(levels))

    rid = data.get("run_id") or {}
    _require_keys("run_id", rid, _RUN_ID_KEYS)
    grammar = rid.get("grammar", GRAMMAR_V1)
    if grammar != GRAMMAR_V1:
        raise TreeError(f"run_id.grammar {grammar!r} unsupported; v1 supports only "
                        f"{GRAMMAR_V1!r}")
    ts_format = rid.get("ts_format", "%y%m%d_%H%M%S")
    ts_pattern, ts_fields = compile_ts_pattern(ts_format)
    tag = rid.get("tag", "optional")
    if tag not in ("required", "optional"):
        raise TreeError(f"run_id.tag must be required|optional, got {tag!r}")

    index_level_names = {n for n, _ in trees["index"].levels}
    links = {}
    for name, spec in (data.get("links") or {}).items():
        if not isinstance(spec, dict):
            raise TreeError(f"links.{name} must be a mapping")
        _require_keys(f"links.{name}", spec, _LINK_KEYS)
        kind = spec.get("kind")
        if kind not in ("data_pointer", "alias"):
            raise TreeError(f"links.{name}.kind must be data_pointer|alias, got {kind!r}")
        if kind == "alias":
            scope = spec.get("scope", "root")
            if scope != "root" and scope not in index_level_names:
                raise TreeError(f"links.{name}.scope {scope!r} must be 'root' or a "
                                f"declared index level {sorted(index_level_names)}")
        else:
            scope = "run"
        links[name] = LinkSpec(name=name, kind=kind, scope=scope,
                               required=bool(spec.get("required", False)))

    rd = data.get("run_dir") or {}
    _require_keys("run_dir", rd, _RUN_DIR_KEYS)
    requires = tuple(rd.get("requires") or [])
    entries_raw = rd.get("entries", None)
    entries = tuple(entries_raw) if entries_raw is not None else None
    eval_pattern = rd.get("eval_pattern", "eval/<mode>_<ts>")
    if "<mode>" not in eval_pattern or "<ts>" not in eval_pattern:
        raise TreeError("run_dir.eval_pattern must contain the <mode> and <ts> placeholders")
    eval_modes = tuple(rd.get("eval_modes") or [])
    for m in eval_modes:
        if not isinstance(m, str) or not _MODE.fullmatch(m):
            raise TreeError(f"run_dir.eval_modes entry {m!r} must be a lowercase token")
    deprecated = []
    for d in rd.get("deprecated") or []:
        if not isinstance(d, dict) or not d.get("pattern"):
            raise TreeError("run_dir.deprecated entries need a non-empty 'pattern'")
        deprecated.append((d["pattern"], d.get("message", "deprecated pattern")))

    walk = data.get("walk") or {}
    _require_keys("walk", walk, _WALK_KEYS)
    ignore = tuple(walk.get("ignore") or [])

    return TreeSchema(version=1, trees=trees, ts_format=ts_format,
                      ts_pattern=ts_pattern, ts_fields=ts_fields, tag=tag,
                      links=links, requires=requires, entries=entries,
                      eval_pattern=eval_pattern, eval_modes=eval_modes,
                      deprecated=tuple(deprecated), ignore=ignore)


DEFAULT_TREE_YAML = """\
# omx tree schema (generic default, written by `omx init`).
# Declares this project's experiment output-tree conventions; every tree verb
# (tree-audit/scaffold/alias/index) validates or generates against it.
# Replace with `omx tree-codify` output once a real tree exists.
# Known v1 limitation: run_id labels are dash-only ([a-z0-9-]); a writer that
# emits underscore-bearing labels gets the label tail attributed to the tag
# (affects only tag-presence checks, never a crash).
version: 1
pending_approval: true
trees:
  index:
    root: experiments
    levels: []
run_id:
  grammar: "<label>[_<tag>]_<ts>"
  ts_format: "%y%m%d_%H%M%S"
  tag: optional
links:
  latest: {kind: alias, scope: root}
run_dir:
  requires: [manifest.json]
  eval_pattern: "eval/<mode>_<ts>"
  eval_modes: [static]
walk:
  ignore: ["legacy", "_*"]
"""
