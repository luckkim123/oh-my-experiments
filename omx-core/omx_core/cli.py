"""omx_core.cli — the `omx` command (Claude-free verbs: ingest, reduce, session-id).

These verbs are pure Python so they are unit-testable from Bash with no Claude
or Isaac dependency. Skills (builds #3-#6) shell out to these.
"""
import argparse
import importlib.metadata
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

from omx_core.ingest.eval_summary import EvalSummaryAdapter
from omx_core.ingest.csv_longform import LongFormCsvAdapter
from omx_core.ingest.tensorboard import TensorboardAdapter
from omx_core.ingest.wandb_offline import WandbAdapter
from omx_core.reduce.summarize import to_dataframe, add_cv
from omx_core.reduce.series import downsample
from omx_core.reduce.plot import line_plot
from omx_core.reduce.promote import promote_plots
from omx_core.evaluator import run_evaluator
from omx_core.decision import decide_outcome, parse_keep_policy
from omx_core.omx_paths import OmxError, OmxPaths, validate_token, resolve_session_id, atomic_path
from omx_core import integrity as _integrity
from datetime import datetime, timezone

from omx_core.loop import queue_pending_launch, read_pending_launch, deadline_passed, compute_deadline
from omx_core.profile import bootstrap_profile, default_metrics
from omx_core.report import parse_findings
from omx_core.coverage import check_coverage, check_cross_run_refs
from omx_core.profile import load_profile_metrics
from omx_core.wiki import ingest as _wiki_ingest, query as _wiki_query, lint as _wiki_lint, storage as _wiki_storage, gc as _wiki_gc


def _finite_or_none(x):
    """Map non-finite floats (nan/inf) to None so json.dumps emits valid JSON null."""
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def _finite_clean(obj):
    """Recursively map every non-finite float in a JSON-shaped structure to None.

    An evaluator may emit a non-finite score (e.g. {"pass": true, "score": NaN});
    that value rides through run_evaluator into the record AND, under
    --keep-policy, into out["decision"]["evaluator"]. json.dumps would emit a bare
    NaN token (valid in Python's lenient reader but rejected by any strict
    consumer: JS JSON.parse, jq). Walking the whole structure cleans both the
    top-level and nested copies without hardcoding key paths."""
    if isinstance(obj, dict):
        return {k: _finite_clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_finite_clean(v) for v in obj]
    return _finite_or_none(obj)


_ADAPTERS = {
    "eval_summary": EvalSummaryAdapter,
    "csv_longform": LongFormCsvAdapter,
    "tensorboard": TensorboardAdapter,
    "wandb": WandbAdapter,
}


def _ingest(path, fmt, max_scalars=None, max_bytes=None):
    if fmt == "npz":
        from omx_core.reduce.series import load_npz
        from omx_core.ingest.base import IngestResult
        arrs = load_npz(path)
        all_keys = set(arrs)
        # only 1-D numeric arrays are plottable series; keep those
        series = {k: v for k, v in arrs.items() if getattr(v, "ndim", 0) == 1}
        return IngestResult(summary=[], series=series,
                            meta={"source": str(path), "format": "npz",
                                  "skipped_nd": sorted(all_keys - set(series))})
    if fmt not in _ADAPTERS:
        raise SystemExit(f"unknown --format {fmt!r}; choose from {sorted(_ADAPTERS) + ['npz']}")
    if fmt == "tensorboard":
        adapter = TensorboardAdapter(max_scalars=max_scalars, max_bytes=max_bytes)
    elif fmt == "eval_summary":
        adapter = EvalSummaryAdapter(max_bytes=max_bytes)
    else:
        adapter = _ADAPTERS[fmt]()
    return adapter.ingest(path)


def _resolve_ingest_bounds(args):
    """Flag > profile ingest_limits > None (adapter default). D12 override slot."""
    max_scalars = getattr(args, "max_scalars", None)
    max_bytes = getattr(args, "max_bytes", None)
    root = getattr(args, "root", None)
    if root and (max_scalars is None or max_bytes is None):
        try:
            limits = load_profile_metrics(root).get("ingest_limits", {}) or {}
        except OmxError:
            # deliberate swallow: --root is an OPTIONAL override slot, so a
            # missing/unbootstrapped profile must not force profile setup —
            # fall through to the adapter defaults instead of loud-failing.
            limits = {}
        if max_scalars is None:
            max_scalars = limits.get("max_scalars")
        if max_bytes is None:
            max_bytes = limits.get("max_bytes")
    return max_scalars, max_bytes


def _add_ingest_bounds(parser, *, with_root: bool):
    parser.add_argument("--max-scalars", type=int, default=None, dest="max_scalars",
                        help="cap TB scalar samples per tag (default 10000)")
    parser.add_argument("--max-bytes", type=int, default=None, dest="max_bytes",
                        help="refuse sources larger than this (default 1 GiB)")
    if with_root:
        parser.add_argument("--root", default=None,
                            help="optional .omx anchor; reads profile ingest_limits")


def _cmd_ingest(args) -> int:
    ms, mb = _resolve_ingest_bounds(args)
    try:
        res = _ingest(args.path, args.format, max_scalars=ms, max_bytes=mb)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps({
        "format": res.meta.get("format"),
        "source": res.meta.get("source"),
        "n_summary": len(res.summary),
        "n_series": len(res.series),
    }))
    return 0


def _cmd_reduce_summarize(args) -> int:
    ms, mb = _resolve_ingest_bounds(args)
    try:
        res = _ingest(args.path, args.format, max_scalars=ms, max_bytes=mb)
    except OmxError as e:
        raise SystemExit(str(e))
    df = to_dataframe(res.summary)
    # GAP A: loud-fail when the requested cv-field is not in the ingested field
    # vocabulary (e.g. user passed an axis name like "roll" instead of a field
    # name like "ss_error").  Guard only fires when at least one record exists
    # so that an empty summary (genuine data absence) still returns [] quietly.
    available_fields = sorted(df["field"].dropna().unique()) if not df.empty else []
    if available_fields and args.cv_field not in available_fields:
        raise SystemExit(
            f"field {args.cv_field!r} not found; available: {available_fields}")
    cv = add_cv(df, base_field=args.cv_field)
    rows = [
        {"dr_level": r.dr_level, "axis": r.axis,
         "mean": _finite_or_none(r["mean"]),
         "std": _finite_or_none(r["std"]),
         "cv": _finite_or_none(r["cv"])}
        for _, r in cv.iterrows()
    ]
    print(json.dumps({"cv_field": args.cv_field, "cv": rows}, allow_nan=False))
    return 0


def _cmd_reduce_tb_final(args) -> int:
    """Print named final-window means for the requested tags as JSON.

    The general, raw-TB-no-hand-read home for citing per-term scalars (e.g. the
    8 Reward/* decomposition terms). An absent tag loud-fails (lists available
    tags) — never a silent 0 — so the caller cross-checks instead of asserting
    'no data' (the engine-output-unverified trap this verb exists to prevent)."""
    from omx_core.reduce.tb_final import final_window_means
    ms, mb = _resolve_ingest_bounds(args)
    try:
        res = _ingest(args.path, args.format, max_scalars=ms, max_bytes=mb)
        final = final_window_means(res.series, args.tag, window=args.window)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps({"window": args.window, "final": final}, allow_nan=False))
    return 0


def _cmd_session_id(args) -> int:
    sid = resolve_session_id(
        explicit=args.session_id,
        env=os.environ.get("OMX_SESSION_ID"),
        autogen=lambda: f"{_now_stamp()}-{os.getpid()}",
    )
    print(sid)
    return 0


def _cmd_doctor(args) -> int:
    from omx_core.doctor import run_doctor
    plugin_root = args.plugin_root or os.environ.get("CLAUDE_PLUGIN_ROOT")
    print(json.dumps(run_doctor(root=args.root, plugin_root=plugin_root)))
    return 0


def _cmd_profile_seal(args) -> int:
    """Record the approved evaluator/launch sha256 seal (#0)."""
    from omx_core.seal import write_seal
    try:
        seal = write_seal(OmxPaths(root=args.root), now=_now_iso())
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(seal))
    return 0


def _cmd_eval(args) -> int:
    """Run an evaluator command, print its contract record (+ optional decision).

    rc 0 when the evaluator produced a graded verdict (status pass|fail);
    rc 1 when the evaluator itself errored (status error) — so Bash callers can
    tell 'graded' from 'broke'. With --keep-policy, also runs decide_outcome and
    embeds a 'decision' block (B5 coupling visible from the CLI). With --root,
    preflights the profile seal (#0) BEFORE running anything: rc 2 if the sealed
    evaluator/launch files were modified since the last `omx profile-seal`.
    """
    from omx_core.seal import check_seal
    if args.root:
        st = check_seal(OmxPaths(root=args.root))
        if st["status"] == "mismatch":
            raise SystemExit(
                f"profile files modified since seal ({st['mismatched']}); run "
                "`omx profile-seal --root <root>` to re-approve as an explicit change")
        if st["status"] == "absent":
            print("WARNING: no profile seal (.omx/profile/seal.json); run "
                  "`omx profile-seal` after approving the profile", file=sys.stderr)
    else:
        print("WARNING: seal check skipped (no --root)", file=sys.stderr)

    rec = run_evaluator(args.command, cwd=args.cwd or os.getcwd(), timeout=args.timeout)
    out = dict(rec)
    if args.keep_policy is not None:
        try:
            policy = parse_keep_policy(args.keep_policy)
        except OmxError as e:
            raise SystemExit(str(e))
        out["decision"] = decide_outcome(policy, args.last_kept_score, rec)
    print(json.dumps(_finite_clean(out), allow_nan=False))
    return 0 if rec["status"] in ("pass", "fail") else 1


def _cmd_plot_summary_bar(args, res) -> int:
    """Render a per-axis bar chart from eval_summary SummaryRecords (GAP B).

    Called from _cmd_plot when --format eval_summary and --view per_axis_bar.
    --series is the field name (e.g. ss_error); one bar per axis, one chart per
    dr_level if multiple levels are present (default: first dr_level found).
    Schema-driven: works for any {dr_level:{axis:{field:value}}} summary.json.
    """
    from omx_core.reduce.plot import bar_plot
    field = args.series
    available_fields = sorted({r.field for r in res.summary if r.field is not None})
    if not available_fields:
        raise SystemExit(
            f"series {field!r} not in source; available: {available_fields}")
    if field not in available_fields:
        raise SystemExit(
            f"series {field!r} not in source; available: {available_fields}")
    try:
        metric = validate_token(args.metric, "metric")
        view = validate_token(args.view, "view")
    except OmxError as e:
        raise SystemExit(str(e))
    # Collect (axis, value) pairs for this field; use first dr_level when multiple exist
    recs_for_field = [r for r in res.summary if r.field == field and r.axis is not None]
    dr_levels = sorted({r.dr_level for r in recs_for_field})
    if not dr_levels:
        raise SystemExit(
            f"no records with field {field!r} and a named axis; available: {available_fields}")
    dr = dr_levels[0]  # default: first level alphabetically
    pairs = sorted((r.axis, r.value) for r in recs_for_field if r.dr_level == dr)
    labels = [p[0] for p in pairs]
    values = [p[1] for p in pairs]
    out = OmxPaths(root=args.root).scratch_plots(session_id=args.session_id) / f"{metric}__{view}.png"
    bar_plot(labels, values, out, title=f"{metric} ({view}, dr={dr})")
    print(json.dumps({"plot": str(out), "metric": metric, "view": view,
                      "dr_level": dr, "n_axes": len(labels)}))
    return 0


def _cmd_plot(args) -> int:
    """Render ONE candidate curve from a series source into scratch/<sid>/plots/.

    Claude-free: the skill picks WHICH series/metric/view; this verb does the
    matplotlib + scratch-path IO (design D8). Output filename = <metric>__<view>.png.
    """
    ms, mb = _resolve_ingest_bounds(args)
    try:
        res = _ingest(args.path, args.format, max_scalars=ms, max_bytes=mb)
    except OmxError as e:
        raise SystemExit(str(e))
    # GAP B: eval_summary is tabular (series={}); intercept for summary-based bar charts
    if res.meta.get("format") == "eval_summary":
        return _cmd_plot_summary_bar(args, res)
    if args.series not in res.series:
        skipped = res.meta.get("skipped_nd", [])
        hint = (f" (NOTE: {args.series!r} is in the file but is N-D; only 1-D arrays are plottable)"
                if args.series in skipped else "")
        raise SystemExit(
            f"series {args.series!r} not in source{hint}; available: {sorted(res.series)[:20]}")
    try:
        metric = validate_token(args.metric, "metric")
        view = validate_token(args.view, "view")
    except OmxError as e:
        raise SystemExit(str(e))
    y = downsample(res.series[args.series])
    step_key = f"_step/{args.series}"
    x = downsample(res.series[step_key]) if step_key in res.series else np.arange(len(y))
    out = OmxPaths(root=args.root).scratch_plots(session_id=args.session_id) / f"{metric}__{view}.png"
    line_plot(x, {args.series: y}, out, title=f"{metric} ({view})")
    print(json.dumps({"plot": str(out), "metric": metric, "view": view,
                      "n_points": int(len(y))}))
    return 0


def _cmd_promote(args) -> int:
    """Promote report-referenced PNGs from scratch into the permanent analysis tree (B3).

    --referenced may be repeated. Loud-fails (rc 2) if any referenced PNG is absent
    in scratch (promote_plots raises OmxError -> SystemExit)."""
    paths = OmxPaths(root=args.root)
    scratch = paths.scratch_plots(session_id=args.session_id)
    dest = paths.analysis_dir(
        args.output_root, args.run_id, args.analysis_id, group=getattr(args, "group", None)
    ) / "plots"
    try:
        moved = promote_plots(scratch, dest, args.referenced)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps({"promoted": [str(p) for p in moved]}))
    return 0


def _cmd_init(args) -> int:
    """Bootstrap .omx/profile/ from the interview-derived metrics (Claude-free).

    The exp-init skill (#3) shells this after the interview; --metrics-json carries
    the interview result, --root anchors .omx/ (design H4). Profile schema validation
    + atomic writes live in profile.bootstrap_profile (D8: enforced by code).
    """
    if args.metrics_json is not None:
        try:
            metrics = json.loads(args.metrics_json)
        except (ValueError, TypeError) as e:
            raise SystemExit(f"--metrics-json is not valid JSON: {e}")
    else:
        metrics = default_metrics()
    paths = OmxPaths(root=args.root)
    try:
        written = bootstrap_profile(
            paths, profile_name=args.profile_name, metrics=metrics, force=args.force)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps({
        "profile_name": args.profile_name,
        "root": str(paths.omx_dir),
        "written": [p.name for p in written],
        "pending_approval": True,
    }))
    return 0


def _cmd_report_parse(args) -> int:
    """Parse an exp-analyze report.md into structured findings (Claude-free).

    The exp-design skill (#5) shells this to read findings without re-implementing
    the tag grammar; exp-loop (#6) reuses it. rc 0 + JSON {n_findings, findings:[]}
    on success; rc 2 (SystemExit) on a missing file or a malformed tag run.

    Consumer boundary (#14): verifies the stamp before parsing. mismatch/no-gates
    loud-fail (rc 2) — a consumer must never read a tampered or ungated report.
    unstamped (pre-0.2.0 legacy) only warns on stderr and still parses (spec 4
    backward-compat); the output JSON carries the integrity status either way."""
    path = args.path
    if not os.path.exists(path):
        raise SystemExit(f"report not found: {path}")
    v = _integrity.verify_report(path)
    if v["status"] in ("mismatch", "no-gates"):
        raise SystemExit(
            f"report integrity {v['status']} — refusing to parse a tampered/ungated "
            "report; re-enter exp-analyze (RE-analysis) so report-coverage re-stamps it")
    if v["status"] == "unstamped":
        print("WARNING: unstamped legacy report (pre-0.2.0); "
              "rc2 promotion earmarked for 0.3.0", file=sys.stderr)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        findings = parse_findings(text)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps({
        "n_findings": len(findings),
        "findings": [
            {"claim": f.claim, "evidence": f.evidence, "confidence": f.confidence}
            for f in findings
        ],
        "integrity": v["status"],
    }))
    return 0


def _cmd_report_verify(args) -> int:
    """STRICT integrity check (#14): rc 2 unless the stamp verifies clean.

    Explicit call gets the strict answer (spec 3.3) — unlike report-parse's
    consumer boundary, 'unstamped' is not tolerated here."""
    if not os.path.exists(args.path):
        raise SystemExit(f"report not found: {args.path}")
    v = _integrity.verify_report(args.path)
    print(json.dumps(v))
    if v["status"] != "ok":
        raise SystemExit(
            f"report integrity {v['status']}"
            + (f" (files: {v['mismatched']})" if v["mismatched"] else "")
            + " — gated deliverables are re-written only through the exp-analyze "
              "RE-analysis path, then re-stamped by report-coverage")
    return 0


def _cmd_report_coverage(args) -> int:
    """Lint a report.md for diagnostic-group + engine-marker completeness (GAP 4).

    Reads the profile's optional groups/engine_markers, checks the report covered
    each declared diagnostic group and cited the training-log engine. rc 0 + JSON
    {ok, missing_groups, engine_cited, ...} when ok; rc 3 (loud-fail) when a group
    was skipped or the engine was never cited, so a 'When done' gate in the skill
    can hard-block a hand-extracted, engine-skipping report. The exact incident:
    a report can touch most vocab via final scalars yet never run the engine."""
    path = args.path
    if not os.path.exists(path):
        raise SystemExit(f"report not found: {path}")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    # baseline regression gate (dr_harder 2026-06-08 incident): when --baseline points
    # at the prior report this one replaces, a shrink (fewer findings/tables, words past
    # tolerance) is a hard fail. Resolve it explicitly OR auto-discover the latest other
    # analysis for the same run when --baseline auto is given.
    baseline_text = None
    if args.baseline:
        bpath = args.baseline if args.baseline != "auto" else _auto_baseline(path)
        if bpath:
            if not os.path.exists(bpath):
                raise SystemExit(f"baseline report not found: {bpath}")
            with open(bpath, encoding="utf-8") as fh:
                baseline_text = fh.read()
    # cross-run reference-value gate (E4 stale-column incident): --cross-run-refs
    # points at a JSON list of refs the report carries forward from OTHER runs (e.g.
    # a 'teacher hard' column). Each is verified for provenance (source eval id cited)
    # + value (matches the source summary.json). The fragile table-parsing that BUILDS
    # the refs is the caller's job (the skill writes refs.json); the core only verifies.
    cross_refs = None
    if args.cross_run_refs:
        if not os.path.exists(args.cross_run_refs):
            raise SystemExit(f"cross-run refs file not found: {args.cross_run_refs}")
        with open(args.cross_run_refs, encoding="utf-8") as fh:
            cross_refs = json.load(fh)
        if not isinstance(cross_refs, list):
            raise SystemExit(
                f"--cross-run-refs must be a JSON list of ref objects, "
                f"got {type(cross_refs).__name__}")
    try:
        profile = load_profile_metrics(args.root)
        res = check_coverage(text, profile, min_coverage=args.min_coverage,
                             baseline_text=baseline_text)
        xref = check_cross_run_refs(text, cross_refs) if cross_refs is not None else None
    except OmxError as e:
        raise SystemExit(str(e))
    out = {
        # overall gate verdict: coverage AND the cross-run-refs gate (when run)
        "ok": res.ok and (xref is None or xref.ok),
        "missing_groups": res.missing_groups,
        "engine_cited": res.engine_cited,
        "checked_groups": res.checked_groups,
        "markers_declared": res.markers_declared,
        # per-group hit/total so the agent sees WHERE coverage is thin (GAP 4b)
        "group_hits": {g: list(ht) for g, ht in res.group_hits.items()},
        "min_coverage": args.min_coverage,
        # GAP E: groups that pass the threshold but have unreferenced tokens — field-level
        # omissions within a passing group that lenient mode would otherwise silently accept.
        "partial_groups": res.partial_groups,
        # dr_harder incident: required sections absent as headings + depth regression
        "missing_sections": res.missing_sections,
        "regression": res.regression,
        # E4 incident: cross-run reference-value gate result (None when not requested)
        "cross_run_refs": (
            {"ok": xref.ok, "uncited": xref.uncited, "mismatched": xref.mismatched}
            if xref is not None else None),
    }
    # #14: stamper = verifier, one call — stamp the sibling manifest when the
    # gates pass AND the report actually lives in an analysis tree (linting a
    # loose copy must not scatter manifest.json files).
    out["stamped"] = False
    if out["ok"] and _integrity.is_analysis_report(path):
        try:
            omx_version = importlib.metadata.version("omx-core")
        except importlib.metadata.PackageNotFoundError:
            omx_version = None
        _integrity.stamp_report(
            path, gates_passed=[g for g, cond in (
                ("coverage", True),
                ("baseline-regression", baseline_text is not None),
                ("cross-run-refs", cross_refs is not None),
            ) if cond],
            now=_now_iso(), omx_version=omx_version)
        out["stamped"] = True
    print(json.dumps(out))
    if res.partial_groups:
        # Warn loudly to stderr so the analyst cannot silently miss sub-group fields.
        # ok remains True (lenient semantics unchanged); this is advisory, not a gate.
        for grp in res.partial_groups:
            hits, total = res.group_hits[grp]
            print(
                f"WARNING: group '{grp}': {hits}/{total} tokens referenced "
                f"— some fields may be missing from the report",
                file=sys.stderr,
            )
    if not out["ok"]:
        # loud-fail so the skill's coverage gate can detect it by exit code
        reasons = []
        if res.missing_groups:
            reasons.append(f"diagnostic groups not referenced: {res.missing_groups}")
        if not res.engine_cited:
            reasons.append(
                "no engine marker cited (report appears hand-extracted, not grounded "
                f"in the engine output {res.markers_declared})")
        if res.missing_sections:
            reasons.append(
                f"required sections missing as headings: {res.missing_sections} "
                "(a whole diagnostic section was dropped — e.g. generalization/OOD)")
        if res.regression is not None and res.regression["is_regression"]:
            r = res.regression
            dropped = [k for k in ("words", "findings", "tables") if r[k]["regressed"]]
            detail = ", ".join(
                f"{k} {r[k]['old']}->{r[k]['new']}" for k in dropped)
            reasons.append(
                f"DEPTH REGRESSION vs baseline ({detail}) — a re-analysis must NOT be "
                "shallower than the report it replaces; use the OLD report as the BASE "
                "and update plots/numbers on top of it, do not rewrite shorter")
        if xref is not None and not xref.ok:
            if xref.mismatched:
                stale = ", ".join(
                    f"{m['label']} reported {m['reported']} but {m['eval_id']} "
                    f"{m['field']} = {m['actual']:.4g}" for m in xref.mismatched)
                reasons.append(
                    f"STALE cross-run reference value(s) ({stale}) — a carried-forward "
                    "reference column must be RE-EXTRACTED from the source eval each "
                    "analysis, never copied from a prior report")
            if xref.uncited:
                uncited = ", ".join(
                    f"{u['label']} (eval {u['eval_id']})" for u in xref.uncited)
                reasons.append(
                    f"UNCITED cross-run reference source(s) ({uncited}) — the report "
                    "must cite the eval id each reference value came from so it is auditable")
        raise SystemExit("report coverage FAILED — " + "; ".join(reasons))
    return 0


def _cmd_report_review(args) -> int:
    """Mechanical review layer (spec 3.4). rc 2 only on missing files; a
    'revise' verdict is data (rc 0) — R1 records reviews, it does not gate."""
    from omx_core.review import review_report
    if not os.path.exists(args.path):
        raise SystemExit(f"report not found: {args.path}")
    with open(args.path, encoding="utf-8") as fh:
        text = fh.read()
    baseline_text = None
    if args.baseline:
        bpath = args.baseline if args.baseline != "auto" else _auto_baseline(args.path)
        if bpath:
            if not os.path.exists(bpath):
                raise SystemExit(f"baseline report not found: {bpath}")
            with open(bpath, encoding="utf-8") as fh:
                baseline_text = fh.read()
    res = review_report(text, baseline_text=baseline_text)
    if args.record_to:
        target = Path(args.record_to) / "review.json"
        with atomic_path(target) as tmp:
            Path(tmp).write_text(json.dumps(res, indent=2), encoding="utf-8")
        res = dict(res, recorded=str(target))
    print(json.dumps(res))
    return 0


def _auto_baseline(report_path: str) -> str | None:
    """Find the most recent OTHER report.md for the same run (sibling analysis dir).

    Layout: <run>/analysis/<analysis_id>/report.md. The baseline is the report.md in
    the lexicographically-latest sibling analysis dir that is NOT the one being linted
    (analysis_id is verb-YYYYMMDD-HHMMSS, so lexicographic order ~= chronological for a
    fixed verb). Returns None if there is no prior sibling (first analysis of the run)."""
    cur_analysis_dir = os.path.dirname(os.path.abspath(report_path))
    analysis_root = os.path.dirname(cur_analysis_dir)
    cur_name = os.path.basename(cur_analysis_dir)
    if not os.path.isdir(analysis_root):
        return None
    siblings = sorted(
        d for d in os.listdir(analysis_root)
        if d != cur_name
        and os.path.isfile(os.path.join(analysis_root, d, "report.md")))
    if not siblings:
        return None
    return os.path.join(analysis_root, siblings[-1], "report.md")


def _cmd_queue_launch(args) -> int:
    """Queue the next training launch as a pending-approval artifact (B8).

    NEVER launches — writes runs/<run_id>/pending-launch.json and prints it.
    queued_at is the real clock, injected here (the core stays time-pure)."""
    paths = OmxPaths(root=args.root)
    now = datetime.now(timezone.utc).isoformat()
    try:
        queue_pending_launch(
            paths, args.run_id,
            proposal_id=args.proposal_id, launch_delta=args.launch_delta,
            gpu_gate=args.gpu_gate, queued_at=now)
        print(json.dumps(read_pending_launch(paths, args.run_id)))
    except OmxError as e:
        raise SystemExit(str(e))
    return 0


def _cmd_loop_status(args) -> int:
    """Report loop status as one JSON: whether the deadline ceiling passed and
    what (if anything) is queued for launch. Claude-free; the skill reads this
    to decide stop-or-continue. --now defaults to the real clock; pass it
    explicitly for deterministic tests.

    Deadline resolution order:
      1. --deadline (explicit ISO-8601) takes precedence.
      2. --max-runtime <seconds>: deadline = now + max_runtime via compute_deadline.
      3. Neither: deadline_passed is None (no ceiling check).
    """
    paths = OmxPaths(root=args.root)
    now = args.now or datetime.now(timezone.utc).isoformat()
    deadline = args.deadline
    try:
        if deadline is None and args.max_runtime is not None:
            deadline = compute_deadline(now, args.max_runtime)
        passed = deadline_passed(deadline, now) if deadline else None
    except OmxError as e:
        raise SystemExit(str(e))
    try:
        pending = read_pending_launch(paths, args.run_id)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps({
        "run_id": args.run_id,
        "now": now,
        "deadline": deadline,
        "deadline_passed": passed,
        "pending_launch": pending,
    }))
    return 0


def _now_stamp() -> str:
    # local wall-clock; deterministic format YYYYMMDD-HHMMSS
    import time
    return time.strftime("%Y%m%d-%H%M%S", time.localtime())


def _now_iso() -> str:
    """Wall-clock now as a NAIVE UTC ISO string (no tz offset).

    The wiki stamps created/updated with this and lint subtracts naive-vs-naive;
    a tz-aware value would make lint's stale-delta raise. Naive-everywhere is the
    wiki's contract (loop.py's aware path is separate)."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _cmd_wiki_add(args) -> int:
    paths = OmxPaths(root=args.root)
    if args.from_report is not None:
        report = Path(args.from_report)
        if not report.exists():
            raise SystemExit(f"report not found: {report}")
        try:
            findings = parse_findings(report.read_text(encoding="utf-8"))
        except OmxError as e:
            raise SystemExit(str(e))
        print(json.dumps({"candidates": [
            {"claim": f.claim, "evidence": f.evidence, "confidence": f.confidence}
            for f in findings
        ]}))
        return 0
    for need in ("title", "category", "content", "confidence"):
        if getattr(args, need) is None:
            raise SystemExit(f"--{need} is required in write mode (omit only with --from-report)")
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    content = args.content
    if content == "-":
        content = sys.stdin.read()
    from omx_core.wiki.quality import QUALITY_FLOOR, score_page
    floor = QUALITY_FLOOR
    try:
        floor = int(load_profile_metrics(args.root).get("wiki_quality_floor", floor))
    except OmxError:
        pass  # no profile yet — built-in floor (D12: override slot, generic default)
    score, reasons = score_page(content, tags, title=args.title)
    confidence = args.confidence
    forced = score < floor and confidence != "low"
    if forced:
        confidence = "low"
    try:
        res = _wiki_ingest.ingest_knowledge(
            paths, now=_now_iso(), title=args.title, content=content,
            tags=tags, category=args.category, confidence=confidence,
            sources=[s.strip() for s in (args.sources or "").split(",") if s.strip()],
            quality_score=score, quality_reasons=reasons)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps({**res, "quality_score": score, "quality_forced_low": forced,
                      "quality_reasons": reasons}))
    return 0


def _cmd_wiki_query(args) -> int:
    paths = OmxPaths(root=args.root)
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()] or None
    try:
        res = _wiki_query.query_wiki(
            paths, now=_now_iso(), text=args.text, tags=tags,
            category=args.category, limit=args.limit)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(res))
    return 0


def _cmd_wiki_lint(args) -> int:
    paths = OmxPaths(root=args.root)
    try:
        res = _wiki_lint.lint_wiki(
            paths, now=_now_iso(), stale_days=args.stale_days,
            max_page_size=args.max_page_size)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(res))
    return 0


def _cmd_wiki_list(args) -> int:
    paths = OmxPaths(root=args.root)
    out = {"pages": [], "corrupt_pages": []}
    for slug in _wiki_storage.list_pages(paths):
        try:
            page = _wiki_storage.read_page(paths, slug)
        except OmxError:
            out["corrupt_pages"].append(slug)
            continue
        if page is not None:
            out["pages"].append({"slug": slug, "title": page.title, "category": page.category})
    print(json.dumps(out))
    return 0


def _cmd_wiki_read(args) -> int:
    """Print one wiki page's FULL text by slug (query=search, read=full text;
    symmetric with list/add). Default emits the '---' frontmatter block + body
    via serialize_page; --no-frontmatter emits only the body. An absent slug
    loud-fails (SystemExit) rather than printing nothing, so callers can tell
    'page absent' from 'page empty'."""
    paths = OmxPaths(root=args.root)
    try:
        page = _wiki_storage.read_page(paths, args.slug)
    except OmxError as e:
        raise SystemExit(str(e))
    if page is None:
        raise SystemExit(f"wiki page not found: {args.slug}")
    if args.no_frontmatter:
        print(page.content)
    else:
        print(_wiki_storage.serialize_page(page))
    return 0


def _cmd_wiki_gc(args) -> int:
    """Read-only gc diagnosis: lint result + page metadata, as one JSON object for
    the skill to read. Touches nothing (the skill judges, gc-apply executes)."""
    paths = OmxPaths(root=args.root)
    try:
        lint_res = _wiki_lint.lint_wiki(paths, now=_now_iso(),
                                        stale_days=args.stale_days,
                                        max_page_size=args.max_page_size)
    except OmxError as e:
        raise SystemExit(str(e))
    pages = []
    for slug in _wiki_storage.list_pages(paths):
        try:
            page = _wiki_storage.read_page(paths, slug)
        except OmxError:
            continue
        if page is None:
            continue
        pages.append({
            "slug": slug, "title": page.title, "category": page.category,
            "updated": page.updated,
            "bytes": len(page.content.encode("utf-8")),
        })
    suggestions = _wiki_gc.suggest_from_lint(lint_res)
    print(json.dumps({"lint": lint_res, "pages": pages, "suggestions": suggestions}))
    return 0


def _cmd_wiki_gc_apply(args) -> int:
    """Parse an approved proposal and two-phase apply it (validate-all, then execute
    under the lock). git tracking is enforced by apply_gc as the recovery path."""
    proposal = Path(args.proposal)
    if not proposal.exists():
        raise SystemExit(f"proposal not found: {proposal}")
    paths = OmxPaths(root=args.root)
    try:
        plan = _wiki_gc.parse_gc_proposal(proposal.read_text(encoding="utf-8"))
        res = _wiki_gc.apply_gc(paths, plan, now=_now_iso(), repo_root=args.root)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(res))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="omx", description="OMX experiment-analysis core")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="normalize a source to IngestResult (prints counts)")
    pi.add_argument("--path", required=True)
    pi.add_argument("--format", required=True)
    _add_ingest_bounds(pi, with_root=True)
    pi.set_defaults(func=_cmd_ingest)

    pr = sub.add_parser("reduce", help="reduction verbs")
    rsub = pr.add_subparsers(dest="reduce_cmd", required=True)
    prs = rsub.add_parser("summarize", help="long-form -> CV table")
    prs.add_argument("--path", required=True)
    prs.add_argument("--format", required=True)
    prs.add_argument("--cv-field", default="ss_error", dest="cv_field")
    _add_ingest_bounds(prs, with_root=True)
    prs.set_defaults(func=_cmd_reduce_summarize)

    prt = rsub.add_parser(
        "tb-final", help="named final-window means for a tag list (TB/series source)")
    prt.add_argument("--path", required=True, help="series source (TB event file / npz / wandb)")
    prt.add_argument("--format", required=True, help="ingest format (e.g. tensorboard)")
    prt.add_argument("--tag", action="append", default=[], dest="tag",
                     help="scalar tag to reduce (repeatable)")
    prt.add_argument("--window", type=int, default=200,
                     help="trailing samples to average (default 200)")
    _add_ingest_bounds(prt, with_root=True)
    prt.set_defaults(func=_cmd_reduce_tb_final)

    ps = sub.add_parser("session-id", help="resolve session id (flag>env>autogen)")
    ps.add_argument("--session-id", default=None, dest="session_id")
    ps.set_defaults(func=_cmd_session_id)

    pdoc = sub.add_parser("doctor", help="read-only environment preflight (install/deps/profile/hooks)")
    pdoc.add_argument("--root", default=None, help="optional .omx anchor to check profile presence")
    pdoc.add_argument("--plugin-root", default=None, dest="plugin_root",
                      help="plugin dir to check hooks presence (default: $CLAUDE_PLUGIN_ROOT)")
    pdoc.set_defaults(func=_cmd_doctor)

    pe = sub.add_parser("eval", help="run an evaluator command, parse {pass,score?} (Claude-free)")
    pe.add_argument("--command", required=True, help="shell command; LAST stdout line must be the JSON verdict")
    pe.add_argument("--cwd", default=None, help="working dir for the command (default: cwd)")
    pe.add_argument("--timeout", type=int, default=600, help="seconds before the evaluator is killed (status=error)")
    pe.add_argument("--keep-policy", default=None, dest="keep_policy",
                    help="pass_only | score_improvement; when set, embeds a decide_outcome block")
    pe.add_argument("--last-kept-score", type=float, default=None, dest="last_kept_score",
                    help="prior baseline score for score_improvement comparison")
    pe.add_argument("--root", default=None, help="optional .omx anchor; enables the profile seal preflight (#0)")
    pe.set_defaults(func=_cmd_eval)

    psl = sub.add_parser("profile-seal",
                         help="seal .omx/profile/{evaluator.sh,launch.sh} sha256 at approval time (#0)")
    psl.add_argument("--root", required=True)
    psl.set_defaults(func=_cmd_profile_seal)

    pp = sub.add_parser("plot", help="render a candidate curve PNG into scratch (Claude-free IO)")
    pp.add_argument("--root", required=True, help="anchor dir under which .omx/ lives")
    pp.add_argument("--session-id", required=True, dest="session_id")
    pp.add_argument("--path", required=True, help="series source (npz/TB/wandb)")
    pp.add_argument("--format", required=True)
    pp.add_argument("--series", required=True, help="series key within the source")
    pp.add_argument("--metric", required=True, help="metric token (output filename field)")
    pp.add_argument("--view", required=True, help="view token (output filename field)")
    _add_ingest_bounds(pp, with_root=False)
    pp.set_defaults(func=_cmd_plot)

    pm = sub.add_parser("promote-plots", help="B3: move report-referenced PNGs scratch->permanent")
    pm.add_argument("--root", required=True, help="anchor dir under which .omx/ lives")
    pm.add_argument("--session-id", required=True, dest="session_id",
                    help="session id whose scratch/<sid>/plots/ holds the candidates")
    pm.add_argument("--output-root", required=True, dest="output_root")
    pm.add_argument("--run-id", required=True, dest="run_id")
    pm.add_argument("--analysis-id", required=True, dest="analysis_id")
    pm.add_argument("--group", default=None,
                    help="optional run-grouping prefix, e.g. rsl_rl/<exp>/dr_harder "
                         "(flat output_root/<run_id>/ when omitted)")
    pm.add_argument("--referenced", action="append", default=[],
                    help="a report-referenced PNG filename; repeat for multiple")
    pm.set_defaults(func=_cmd_promote)

    pn = sub.add_parser("init", help="bootstrap .omx/profile/ from interview metrics (Claude-free)")
    pn.add_argument("--root", required=True, help="anchor dir under which .omx/ lives (design H4)")
    pn.add_argument("--profile-name", default="isaaclab", dest="profile_name",
                    help="committed reference profile to seed evaluator.sh from")
    pn.add_argument("--metrics-json", default=None, dest="metrics_json",
                    help="metrics.yaml content as a JSON object; omitted = built-in defaults")
    pn.add_argument("--force", action="store_true", help="overwrite an existing profile")
    pn.set_defaults(func=_cmd_init)

    prp = sub.add_parser("report-parse", help="parse exp-analyze report.md -> JSON findings (Claude-free)")
    prp.add_argument("--path", required=True, help="path to an exp-analyze report.md")
    prp.set_defaults(func=_cmd_report_parse)

    prv = sub.add_parser(
        "report-verify",
        help="recompute report sha256 vs the manifest stamp (strict; rc 2 on any deviation)")
    prv.add_argument("--path", required=True, help="report.md or its analysis dir")
    prv.set_defaults(func=_cmd_report_verify)

    prc = sub.add_parser(
        "report-coverage",
        help="lint report.md for diagnostic-group + engine-marker completeness (GAP 4; loud-fail)")
    prc.add_argument("--path", required=True, help="path to an exp-analyze report.md")
    prc.add_argument("--root", required=True, help="workspace root holding .omx/profile/metrics.yaml")
    prc.add_argument(
        "--min-coverage", type=float, default=None, dest="min_coverage",
        help="strict mode: require this FRACTION (0<f<=1) of each group's tokens to be "
             "referenced, not just >=1. Omit for the lenient default (>=1 token per group).")
    prc.add_argument(
        "--baseline", default=None,
        help="prior report.md this one replaces (dr_harder depth-regression gate): a "
             "re-analysis that drops findings/tables or shrinks words past tolerance "
             "loud-fails. Pass a path, or 'auto' to use the latest sibling analysis of "
             "the same run. Omit to skip the regression check (first-time analysis).")
    prc.add_argument(
        "--cross-run-refs", default=None, dest="cross_run_refs",
        help="path to a JSON list of cross-run reference cells the report carries from "
             "OTHER runs (e.g. a 'teacher hard' column). Each ref = {label, summary_path, "
             "field, reported_value}. The gate (E4 stale-column incident) verifies the "
             "source eval id is CITED and the value MATCHES the source summary.json — a "
             "stale carried-over value loud-fails. Omit to skip the cross-run-ref check.")
    prc.set_defaults(func=_cmd_report_coverage)

    prr = sub.add_parser("report-review",
                         help="deterministic critic checklist (spec 3.4; records, never gates)")
    prr.add_argument("--path", required=True, help="path to a report.md")
    prr.add_argument("--baseline", default=None,
                     help="prior report for the depth check; 'auto' = latest sibling analysis")
    prr.add_argument("--record-to", default=None, dest="record_to",
                     help="analysis dir to write review.json into")
    prr.set_defaults(func=_cmd_report_review)

    pq = sub.add_parser("queue-launch",
                        help="queue the next training launch as pending-approval (B8; never fires)")
    pq.add_argument("--root", required=True)
    pq.add_argument("--run-id", required=True)
    pq.add_argument("--proposal-id", required=True)
    pq.add_argument("--launch-delta", required=True)
    pq.add_argument("--gpu-gate", required=True)
    pq.set_defaults(func=_cmd_queue_launch)

    pl = sub.add_parser("loop-status",
                        help="report deadline-ceiling + pending-launch as JSON (Claude-free)")
    pl.add_argument("--root", required=True)
    pl.add_argument("--run-id", required=True)
    pl.add_argument("--deadline", default=None,
                    help="ISO-8601 deadline; omit to skip the ceiling check")
    pl.add_argument("--now", default=None,
                    help="ISO-8601 now (defaults to the real clock; pass for tests)")
    pl.add_argument("--max-runtime", type=int, default=None, dest="max_runtime",
                    help="seconds; when --deadline is omitted, the deadline is "
                         "computed as now + max-runtime (the leaving-work ceiling)")
    pl.set_defaults(func=_cmd_loop_status)

    pw = sub.add_parser("wiki", help="workspace knowledge wiki (keyword-indexed, no embeddings)")
    wsub = pw.add_subparsers(dest="wiki_cmd", required=True)

    pwa = wsub.add_parser("add", help="add/merge a page, OR --from-report to extract candidates")
    pwa.add_argument("--root", required=True)
    pwa.add_argument("--title", default=None)
    pwa.add_argument("--category", default=None)
    pwa.add_argument("--tags", default=None, help="comma-separated")
    pwa.add_argument("--confidence", default=None, choices=["high", "medium", "low"])
    pwa.add_argument("--content", default=None, help="content text, or '-' for stdin")
    pwa.add_argument("--sources", default=None, help="comma-separated source ids")
    pwa.add_argument("--from-report", default=None, dest="from_report",
                     help="extract-only: print [FINDING] candidates from a report.md, write nothing")
    pwa.set_defaults(func=_cmd_wiki_add)

    pwq = wsub.add_parser("query", help="keyword + tag search (tag>title>content, CJK-aware)")
    pwq.add_argument("--root", required=True)
    pwq.add_argument("text", help="query text")
    pwq.add_argument("--tags", default=None, help="comma-separated tag filter")
    pwq.add_argument("--category", default=None)
    pwq.add_argument("--limit", type=int, default=20)
    pwq.set_defaults(func=_cmd_wiki_query)

    pwl = wsub.add_parser("lint", help="audit pages (orphan/stale/broken-ref/oversized), report-only")
    pwl.add_argument("--root", required=True)
    pwl.add_argument("--stale-days", type=int, default=30, dest="stale_days")
    pwl.add_argument("--max-page-size", type=int, default=10240, dest="max_page_size")
    pwl.set_defaults(func=_cmd_wiki_lint)

    pwls = wsub.add_parser("list", help="catalog of pages (slug/title/category)")
    pwls.add_argument("--root", required=True)
    pwls.set_defaults(func=_cmd_wiki_list)

    pwr = wsub.add_parser("read", help="print one page's full text by slug (loud-fail if absent)")
    pwr.add_argument("--root", required=True)
    pwr.add_argument("--slug", required=True, help="page slug (with or without '.md')")
    pwr.add_argument("--no-frontmatter", action="store_true", dest="no_frontmatter",
                     help="emit only the body, omitting the '---' frontmatter block")
    pwr.set_defaults(func=_cmd_wiki_read)

    pwg = wsub.add_parser("gc", help="read-only gc diagnosis (lint + page metadata as JSON); "
                                     "first step of the delete/merge path")
    pwg.add_argument("--root", required=True)
    pwg.add_argument("--stale-days", type=int, default=30, dest="stale_days")
    pwg.add_argument("--max-page-size", type=int, default=10240, dest="max_page_size")
    pwg.set_defaults(func=_cmd_wiki_gc)

    pwga = wsub.add_parser("gc-apply",
                           help="apply an approved wiki-gc proposal (two-phase, git-guarded) -- "
                                "THIS is how you delete/merge pages; there is no separate 'delete' "
                                "subcommand by design (add is append-merge, removal is git-guarded gc)")
    pwga.add_argument("--root", required=True)
    pwga.add_argument("--proposal", required=True, help="path to the approved wiki-gc proposal .md")
    pwga.set_defaults(func=_cmd_wiki_gc_apply)

    return p


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return args.func(args)
    except SystemExit as e:
        if isinstance(e.code, int):
            return e.code
        # Non-int code = a loud-fail message a handler raised via SystemExit(str).
        # main() intercepts SystemExit, so the interpreter never gets to print it;
        # surface it on stderr ourselves (loud-fail discipline) and map to rc 2.
        if e.code is not None:
            print(str(e.code), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
