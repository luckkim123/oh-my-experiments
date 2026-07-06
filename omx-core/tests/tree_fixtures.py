"""Synthetic experiment trees for the R2 tree-verb tests (D12: synthetic vocab).

Three shapes: grouped 2-tree (workspace-shaped), flat generic (default-instance
shaped), violation zoo (one planted violation per audit check T1-T12).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from omx_core.tree import load_tree_schema

GROUPED_TREE_YAML = """\
version: 1
trees:
  index:
    root: experiments
    levels: [framework, exp, "camp?"]
  data:
    root: heavy/fw
    levels: [exp]
run_id:
  grammar: "<label>[_<tag>]_<ts>"
  ts_format: "%y%m%d_%H%M%S"
  tag: required
links:
  train:  {kind: data_pointer, required: true}
  latest: {kind: alias, scope: camp}
run_dir:
  requires: [manifest.json]
  entries: [config, analysis]
  eval_pattern: "eval/<mode>_<ts>"
  eval_modes: [static, periodic]
  deprecated:
    - {pattern: "eval_dr", message: "pre-standard fallback dir"}
walk:
  ignore: ["legacy", "_*"]
"""

FLAT_TREE_YAML = """\
version: 1
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


def _schema(base: Path, text: str):
    fp = base / "tree.yaml"
    fp.write_text(text, encoding="utf-8")
    return load_tree_schema(fp)


def _mk_run(run_dir: Path, *, data_dir: Path | None = None, manifest: bool = True,
            entries=("config",), evals=("static_260601_130000",)) -> Path:
    run_dir.mkdir(parents=True)
    if manifest:
        (run_dir / "manifest.json").write_text(json.dumps(
            {"run_id": run_dir.name, "status": "completed",
             "created": "2026-06-01T12:00:00"}))
    for e in entries:
        (run_dir / e).mkdir()
    for ev in evals:
        (run_dir / "eval" / ev).mkdir(parents=True)
    if data_dir is not None:
        data_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "train").symlink_to(os.path.relpath(data_dir, run_dir))
    return run_dir


def build_grouped_tree(base: Path) -> dict:
    """Two runs under experiments/fw/exp_a/camp_a/, mirrored heavy dirs,
    a `latest` alias, plus legacy/ and _backup/ noise that must be skipped."""
    schema = _schema(base, GROUPED_TREE_YAML)
    camp = base / "experiments" / "fw" / "exp_a" / "camp_a"
    d1 = base / "heavy" / "fw" / "exp_a" / "260601_120000_tune1"
    d2 = base / "heavy" / "fw" / "exp_a" / "260602_120000_tune2"
    r1 = _mk_run(camp / "alpha_tune1_260601_120000", data_dir=d1)
    r2 = _mk_run(camp / "alpha_tune2_260602_120000", data_dir=d2)
    (camp / "latest").symlink_to(r2.name)
    (base / "experiments" / "legacy" / "oldrun").mkdir(parents=True)
    _mk_run(base / "experiments" / "_backup" / "alpha_old_260501_120000",
            data_dir=None, manifest=True)
    return {"schema": schema, "runs": [r1, r2], "camp": camp,
            "data_dirs": [d1, d2]}


def build_flat_tree(base: Path) -> dict:
    """Default-instance shape: runs directly under experiments/, no data tree.
    One run has NO manifest — it must still be detected (predicate clause c)."""
    schema = _schema(base, FLAT_TREE_YAML)
    root = base / "experiments"
    r1 = _mk_run(root / "alpha_260601_120000", entries=())
    r2 = (root / "alpha_260602_120000")           # grammar-only run: no manifest
    r2.mkdir(parents=True)
    (root / "latest").symlink_to(r2.name)
    return {"schema": schema, "runs": [r1, r2], "root": root}


def build_violation_zoo(base: Path) -> dict:
    """Grouped shape with one planted violation per audit check (spec 2.3)."""
    schema = _schema(base, GROUPED_TREE_YAML)
    camp = base / "experiments" / "fw" / "exp_a" / "camp_a"
    heavy = base / "heavy" / "fw" / "exp_a"
    zoo = {}
    # clean control run
    zoo["ok"] = _mk_run(camp / "alpha_good_260601_120000",
                        data_dir=heavy / "260601_120000_good")
    # T1: required data_pointer entry missing
    zoo["t1"] = _mk_run(camp / "alpha_nolink_260601_130000", data_dir=None)
    # T2: dangling data_pointer
    t2 = _mk_run(camp / "alpha_dangle_260601_140000", data_dir=None)
    (t2 / "train").symlink_to("../../../../../heavy/fw/exp_a/gone_260601_140000")
    zoo["t2"] = t2
    # T3: data_pointer escapes the declared data tree
    t3 = _mk_run(camp / "alpha_escape_260601_150000", data_dir=None)
    outside = base / "elsewhere" / "d"
    outside.mkdir(parents=True)
    (t3 / "train").symlink_to(os.path.relpath(outside, t3))
    zoo["t3"] = t3
    # T4: dangling alias
    (camp / "baseline_dangling").mkdir()          # decoy dir, not symlink
    (camp / "latest").symlink_to("alpha_gone_260601_160000")
    # T5: alias pointing outside its scope (camp_b's latest targets a camp_a run)
    camp_b = base / "experiments" / "fw" / "exp_a" / "camp_b"
    other = _mk_run(camp_b / "alpha_other_260601_170000",
                    data_dir=heavy / "260601_170000_other")
    zoo["t5_target"] = other
    (camp_b / "latest").symlink_to("../camp_a/alpha_good_260601_120000")
    zoo["t5"] = camp_b / "latest"
    # T6: run-shaped dir at wrong depth (missing camp level is fine — optional;
    # missing exp AND camp is a depth violation)
    zoo["t6"] = _mk_run(base / "experiments" / "fw" / "alpha_shallow_260601_180000",
                        data_dir=None, manifest=True)
    # T7: grammar violation — tag required but absent
    zoo["t7"] = _mk_run(camp / "alpha_260601_190000", data_dir=heavy / "260601_190000_notag")
    # T8: requires file missing (detected via data_pointer)
    t8 = _mk_run(camp / "alpha_noman_260601_200000", manifest=False,
                 data_dir=heavy / "260601_200000_noman")
    zoo["t8"] = t8
    # T9: undeclared entry
    t9 = _mk_run(camp / "alpha_extra_260601_210000", data_dir=heavy / "260601_210000_extra")
    (t9 / "scratchpile").mkdir()
    zoo["t9"] = t9
    # T10: deprecated pattern hit
    t10 = _mk_run(camp / "alpha_depr_260601_220000", data_dir=heavy / "260601_220000_depr")
    (t10 / "eval_dr").mkdir()
    zoo["t10"] = t10
    # T11: eval leaf not matching pattern/modes
    t11 = _mk_run(camp / "alpha_badev_260601_230000", data_dir=heavy / "260601_230000_badev",
                  evals=("weird_260601_230500", "static_notats"))
    zoo["t11"] = t11
    # T12: data run with no index counterpart
    (heavy / "260603_120000_unindexed").mkdir(parents=True)
    zoo["schema"] = schema
    zoo["camp"] = camp
    return zoo
