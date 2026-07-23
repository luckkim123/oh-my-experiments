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
from datetime import datetime
from pathlib import Path

from omx_core import clock
from omx_core import integrity as _integrity
from omx_core.coverage import check_coverage, check_cross_run_refs
from omx_core.decision import decide_outcome, parse_keep_policy, seed_stats

# numpy/pandas/matplotlib (and the adapter/reduce modules that pull them in)
# are lazy-imported inside the verbs that actually need them (omx-1 audit fix):
# metadata-only verbs (doctor, session-id, wiki list) must not pay their ~250ms
# import cost, which otherwise eats most of the hook backlog-fetch budget.
from omx_core.evaluator import run_evaluator
from omx_core.loop import compute_deadline, deadline_passed, queue_pending_launch, read_pending_launch
from omx_core.omx_paths import OmxError, OmxPaths, atomic_path, resolve_session_id, validate_token
from omx_core.profile import bootstrap_profile, default_metrics, load_profile_metrics
from omx_core.report import parse_findings
from omx_core.wiki import gc as _wiki_gc
from omx_core.wiki import ingest as _wiki_ingest
from omx_core.wiki import lint as _wiki_lint
from omx_core.wiki import query as _wiki_query
from omx_core.wiki import storage as _wiki_storage
from omx_core.wiki.types import BLOCKING_STATUSES as _WIKI_BLOCKING_STATUSES
from omx_core.wiki.types import STATUSES as _WIKI_STATUSES


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


def _resolved_root(args) -> str:
    """--root else the #13 ladder (explicit > OMX_STATE_DIR > marker > git > cwd)."""
    root = getattr(args, "root", None)
    if root:
        return root
    from omx_core.root import resolve_omx_root
    return str(resolve_omx_root()[0])


def _adapters():
    """Lazily import + build the format->adapter registry (numpy-backed)."""
    from omx_core.ingest.csv_longform import LongFormCsvAdapter
    from omx_core.ingest.eval_summary import EvalSummaryAdapter
    from omx_core.ingest.tensorboard import TensorboardAdapter
    from omx_core.ingest.wandb_offline import WandbAdapter
    return {
        "eval_summary": EvalSummaryAdapter,
        "csv_longform": LongFormCsvAdapter,
        "tensorboard": TensorboardAdapter,
        "wandb": WandbAdapter,
    }


def _ingest(path, fmt, max_scalars=None, max_bytes=None):
    if fmt == "npz":
        from omx_core.ingest.base import IngestResult
        from omx_core.reduce.series import load_npz
        arrs = load_npz(path)
        all_keys = set(arrs)
        # only 1-D numeric arrays are plottable series; keep those
        series = {k: v for k, v in arrs.items() if getattr(v, "ndim", 0) == 1}
        return IngestResult(summary=[], series=series,
                            meta={"source": str(path), "format": "npz",
                                  "skipped_nd": sorted(all_keys - set(series))})
    adapters = _adapters()
    if fmt not in adapters:
        raise SystemExit(f"unknown --format {fmt!r}; choose from {sorted(adapters) + ['npz']}")
    if fmt == "tensorboard":
        adapter = adapters["tensorboard"](max_scalars=max_scalars, max_bytes=max_bytes)
    elif fmt == "eval_summary":
        adapter = adapters["eval_summary"](max_bytes=max_bytes)
    else:
        adapter = adapters[fmt]()
    return adapter.ingest(path)


def _resolve_ingest_bounds(args):
    """Flag > profile ingest_limits > None (adapter default). D12 override slot."""
    max_scalars = getattr(args, "max_scalars", None)
    max_bytes = getattr(args, "max_bytes", None)
    root = getattr(args, "root", None) or None
    if root is None:
        root = _resolved_root(args)
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
    from omx_core.reduce.summarize import add_cv, to_dataframe
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


def _cmd_card_check(args) -> int:
    """Cross-repo card-currency guard (D-R5-4). rc 0 + {ok:true,...} on parity;
    rc 2 + a failures list on drift; rc 2 actionable when the card or plugin.json
    is unreachable. DETECTS only — updating the card is an omha-repo edit."""
    from omx_core.cardcheck import run_card_check
    try:
        out = run_card_check(card_path=args.card, plugin_root=args.plugin_root)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(out))
    return 0 if out["ok"] else 2


def _cmd_profile_seal(args) -> int:
    """Record the approved evaluator/launch sha256 seal (#0)."""
    from omx_core.seal import write_seal
    try:
        seal = write_seal(OmxPaths(root=_resolved_root(args)), now=clock.now_iso())
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(seal))
    return 0


def _aggregate_seed_evaluations(recs: list) -> dict:
    """Combine N per-seed run_evaluator records (N>=2) into one evaluation dict
    for decide_outcome's opt-in significance gate (--seeds).

    Any per-seed error -> aggregate status=error (can't trust seed-noise stats
    built on a broken run; surfaces the first error verbatim). Any per-seed
    fail -> aggregate status=fail (can't cherry-pick only the passing seeds).
    All pass with a numeric score on every seed -> score becomes the mean and
    score_std/score_n/seed_scores are attached (stdlib statistics via
    decision.seed_stats, the add_cv mean+std convention without pandas). All
    pass but at least one seed has no score -> scoreless, same as a single
    run without a score (decide_outcome's existing 'ambiguous' branch)."""
    errored = next((r for r in recs if r["status"] == "error"), None)
    if errored is not None:
        return dict(errored)
    failed = next((r for r in recs if not r.get("pass")), None)
    if failed is not None:
        return dict(failed)
    out = dict(recs[-1])
    scores = [r.get("score") for r in recs]
    if all(isinstance(s, (int, float)) and not isinstance(s, bool) for s in scores):
        mean, std, n = seed_stats(scores)
        out["score"] = mean
        out["score_std"] = std
        out["score_n"] = n
        out["seed_scores"] = scores
    else:
        out.pop("score", None)
    return out


def _cmd_eval(args) -> int:
    """Run an evaluator command, print its contract record (+ optional decision).

    rc 0 when the evaluator produced a graded verdict (status pass|fail);
    rc 1 when the evaluator itself errored (status error) — so Bash callers can
    tell 'graded' from 'broke'. With --keep-policy, also runs decide_outcome and
    embeds a 'decision' block (B5 coupling visible from the CLI). With --root,
    preflights the profile seal (#0) BEFORE running anything: rc 2 if the sealed
    evaluator/launch files were modified since the last `omx profile-seal`.

    --seeds N (opt-in, N>=2): runs --command N times instead of once and gates
    on mean±std across seeds (decide_outcome's significance gate) instead of a
    single lucky/unlucky draw. Default (no --seeds) is unchanged: one run, bare
    score comparison — this flag adds a path, it doesn't touch the old one.
    """
    from omx_core.seal import check_seal
    if args.root:
        st = check_seal(OmxPaths(root=_resolved_root(args)))
        if st["status"] == "mismatch":
            raise SystemExit(
                f"profile files modified since seal ({st['mismatched']}); run "
                "`omx profile-seal --root <root>` to re-approve as an explicit change")
        if st["status"] == "absent":
            print("WARNING: no profile seal (.omx/profile/seal.json); run "
                  "`omx profile-seal` after approving the profile", file=sys.stderr)
    else:
        print("WARNING: seal check skipped (no --root)", file=sys.stderr)

    if args.seeds is not None and args.seeds < 1:
        raise SystemExit(f"--seeds must be >= 1, got {args.seeds}")
    if args.seeds and args.seeds > 1:
        recs = [run_evaluator(args.command, cwd=args.cwd or os.getcwd(), timeout=args.timeout)
                for _ in range(args.seeds)]
        rec = _aggregate_seed_evaluations(recs)
    else:
        rec = run_evaluator(args.command, cwd=args.cwd or os.getcwd(), timeout=args.timeout)
    out = dict(rec)
    if args.keep_policy is not None:
        try:
            policy = parse_keep_policy(args.keep_policy)
        except OmxError as e:
            raise SystemExit(str(e))
        out["decision"] = decide_outcome(policy, args.last_kept_score, rec)
    print(json.dumps(_finite_clean(out), allow_nan=False))
    # R4 #27: on an evaluator error, auto-append a low-confidence debugging wiki
    # stub keyed by fault class (append-merge -> recurrence strengthens ONE
    # page). Only with --root (needs a resolvable .omx); NEVER fatal — grading
    # must not break on knowledge plumbing.
    if rec.get("status") == "error" and args.root:
        try:
            from omx_core.wiki.ingest import ingest_knowledge
            fault = rec.get("fault_class") or "unknown"
            body = (
                f"Command: {rec.get('command')}\n"
                f"Exit code: {rec.get('exit_code')}\n"
                f"Parse error: {rec.get('parse_error')}\n"
                f"Ran at: {rec.get('ran_at')}\n"
                f"Cwd: {args.cwd or os.getcwd()}\n")
            ingest_knowledge(
                OmxPaths(root=_resolved_root(args)), now=clock.now_iso_naive(),
                title=f"evaluator fault {fault}", content=body,
                tags=["auto-captured", "evaluator-fault", fault],
                category="debugging", confidence="low", sources=[])
        except Exception as e:  # never fatal (D-R4-5)
            print(f"WARNING: evaluator-fault wiki capture failed: {e}", file=sys.stderr)
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
    out = OmxPaths(root=_resolved_root(args)).scratch_plots(session_id=args.session_id) / f"{metric}__{view}.png"
    bar_plot(labels, values, out, title=f"{metric} ({view}, dr={dr})")
    print(json.dumps({"plot": str(out), "metric": metric, "view": view,
                      "dr_level": dr, "n_axes": len(labels)}))
    return 0


def _cmd_plot(args) -> int:
    """Render ONE candidate curve from a series source into scratch/<sid>/plots/.

    Claude-free: the skill picks WHICH series/metric/view; this verb does the
    matplotlib + scratch-path IO (design D8). Output filename = <metric>__<view>.png.
    """
    import numpy as np

    from omx_core.reduce.plot import line_plot
    from omx_core.reduce.series import downsample
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
    out = OmxPaths(root=_resolved_root(args)).scratch_plots(session_id=args.session_id) / f"{metric}__{view}.png"
    line_plot(x, {args.series: y}, out, title=f"{metric} ({view})")
    print(json.dumps({"plot": str(out), "metric": metric, "view": view,
                      "n_points": int(len(y))}))
    return 0


def _cmd_promote(args) -> int:
    """Promote report-referenced PNGs from scratch into the permanent analysis tree (B3).

    --referenced may be repeated. Loud-fails (rc 2) if any referenced PNG is absent
    in scratch (promote_plots raises OmxError -> SystemExit)."""
    from omx_core.reduce.promote import promote_plots
    paths = OmxPaths(root=_resolved_root(args))
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
    paths = OmxPaths(root=_resolved_root(args))
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


def _cmd_tree_codify(args) -> int:
    """Infer tree.yaml from an existing tree (census; pending approval; spec 2.2)."""
    from omx_core.tree import load_tree_schema
    from omx_core.tree_ops import codify_tree
    root = _resolved_root(args)
    target = OmxPaths(root=root).tree_yaml()
    if target.exists() and not args.force:
        raise SystemExit(
            f"{target} exists; pass --force to regenerate (tree-codify owns replacement)")
    try:
        text, report = codify_tree(Path(root), index_root=args.index_root,
                                   data_root=args.data_root)
    except OmxError as e:
        raise SystemExit(str(e))
    with atomic_path(target) as tmp:
        Path(tmp).write_text(text, encoding="utf-8")
    load_tree_schema(target)  # round-trip guard: loader must accept our own output
    print(json.dumps({"written": str(target), "pending_approval": True,
                      "report": report}))
    return 0


def _cmd_tree_audit(args) -> int:
    """Walk the declared trees against tree.yaml; report-only (spec 2.3)."""
    from omx_core.tree import load_tree_schema
    from omx_core.tree_audit import audit_tree
    root = _resolved_root(args)
    try:
        schema = load_tree_schema(OmxPaths(root=root).tree_yaml())
        res = audit_tree(schema, Path(root))
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(res))
    if args.strict and res["counts"]["error"] > 0:
        raise SystemExit(f"tree-audit: {res['counts']['error']} error(s) under --strict")
    return 0


def _cmd_tree_scaffold(args) -> int:
    """Mint a run skeleton or an eval leaf per tree.yaml (spec 2.4; D4-safe)."""
    from omx_core.tree import load_tree_schema
    from omx_core.tree_ops import scaffold_eval, scaffold_run
    root = _resolved_root(args)
    try:
        schema = load_tree_schema(OmxPaths(root=root).tree_yaml())
        if args.eval_for is not None:
            if args.mode is None:
                raise SystemExit("--mode is required with --eval-for")
            # BY DESIGN local-naive: a human-facing directory NAME, never compared (D-R5-5).
            ts = args.ts or datetime.now().strftime(schema.ts_format)
            out = scaffold_eval(schema, Path(root), args.eval_for, args.mode,
                                now_ts=ts)
        else:
            if args.run_id is None:
                raise SystemExit("--run-id (or --eval-for) is required")
            out = scaffold_run(schema, Path(root), args.run_id,
                               under=args.under or "", data_dir=args.data_dir)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps({"created": str(out)}))
    return 0


def _cmd_tree_alias(args) -> int:
    """Manage declared alias symlinks (atomic re-point; spec 2.5)."""
    from omx_core.tree import load_tree_schema
    from omx_core.tree_ops import list_aliases, set_alias
    root = _resolved_root(args)
    try:
        schema = load_tree_schema(OmxPaths(root=root).tree_yaml())
        if args.list:
            print(json.dumps({"aliases": list_aliases(schema, Path(root))}))
            return 0
        if not args.name or not args.run:
            raise SystemExit("--name and --run are required (or --list)")
        print(json.dumps(set_alias(schema, Path(root), args.name, args.run,
                                   scope_path=args.scope_path)))
    except OmxError as e:
        raise SystemExit(str(e))
    return 0


def _cmd_tree_index(args) -> int:
    """Regenerate (or --check) the generated INDEX.md at the index root (spec 2.6)."""
    from omx_core.tree import load_tree_schema
    from omx_core.tree_ops import write_index
    root = _resolved_root(args)
    try:
        schema = load_tree_schema(OmxPaths(root=root).tree_yaml())
        res = write_index(schema, Path(root), check=args.check, adopt=args.adopt)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(res))
    if args.check and res["stale"]:
        raise SystemExit("INDEX.md is stale — rerun `omx tree-index` to regenerate")
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
    {ok, missing_groups, engine_cited, ...} when ok; rc 2 (loud-fail) when a group
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
        profile = load_profile_metrics(_resolved_root(args))
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
        stamp_now = clock.now_iso()
        _integrity.stamp_report(
            path, gates_passed=[g for g, cond in (
                ("coverage", True),
                ("baseline-regression", baseline_text is not None),
                ("cross-run-refs", cross_refs is not None),
            ) if cond],
            now=stamp_now, omx_version=omx_version)
        out["stamped"] = True
        # spec 2.2: record the stamped report for session-end wiki capture.
        # Advisory — a ledger append failure must not fail the coverage verb.
        try:
            ledger = OmxPaths(root=_resolved_root(args)).produced_reports_ledger()
            ledger.parent.mkdir(parents=True, exist_ok=True)
            with open(ledger, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(
                    {"report": str(Path(path).resolve()), "stamped_at": stamp_now}) + "\n")
        except OSError as e:
            print(f"WARNING: produced-reports ledger append failed: {e}",
                  file=sys.stderr)
        # v0.8.0 campaign liveness: gating a report also records an `analyzed`
        # campaign event (auto-inits the group campaign). Advisory like the
        # produced-reports append — never fails the gate.
        try:
            from omx_core.campaign import record_analyzed
            cres = record_analyzed(OmxPaths(root=_resolved_root(args)), path,
                                   now=stamp_now)
            out["campaign_event"] = cres["status"]
        except (OmxError, OSError, ValueError) as e:
            print(f"WARNING: campaign analyzed-event append failed: {e}",
                  file=sys.stderr)
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


def _cmd_proposal_lint(args) -> int:
    """Gate the discriminating-prediction contract (spec 3.10; loud-fail)."""
    from omx_core.proposal import lint_proposal
    if not os.path.exists(args.path):
        raise SystemExit(f"proposal not found: {args.path}")
    with open(args.path, encoding="utf-8") as fh:
        res = lint_proposal(fh.read())
    print(json.dumps(res))
    if not res["ok"]:
        raise SystemExit("proposal lint FAILED — "
                         + "; ".join(i["rule"] for i in res["issues"]))
    return 0


def _cmd_probe_novelty(args) -> int:
    """Warn-only novelty scan (spec 3.10): wiki + past proposals. Never fails."""
    from omx_core.proposal import jaccard, probe_tokens
    from omx_core.wiki.query import query_wiki
    if args.path and args.proposal:
        raise SystemExit("pass only one of --path/--proposal")
    if args.path:
        args.proposal = args.path
    if not args.proposal:
        raise SystemExit("--path is required")
    if not os.path.exists(args.proposal):
        raise SystemExit(f"proposal not found: {args.proposal}")
    with open(args.proposal, encoding="utf-8") as fh:
        toks = probe_tokens(fh.read())
    top = " ".join(sorted(toks)[:8])
    try:
        hits = query_wiki(OmxPaths(root=_resolved_root(args)), now=clock.now_iso_naive(), text=top,
                          tags=None, category=None, limit=5)
    except OmxError:
        hits = {"matches": []}
    similar = []
    if args.proposals_dir and os.path.isdir(args.proposals_dir):
        for name in sorted(os.listdir(args.proposals_dir)):
            fp = os.path.join(args.proposals_dir, name)
            if not name.endswith(".md") or os.path.abspath(fp) == os.path.abspath(args.proposal):
                continue
            with open(fp, encoding="utf-8") as fh:
                j = jaccard(toks, probe_tokens(fh.read()))
            if j >= 0.3:
                similar.append({"path": fp, "jaccard": round(j, 3)})
    ledger_hits = []
    lp = OmxPaths(root=_resolved_root(args))
    camp_root = lp.omx_dir / "campaigns"
    if camp_root.is_dir():
        for led in sorted(camp_root.glob("*/ledger.jsonl")):
            for line in led.read_text(encoding="utf-8").splitlines():
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                # launched is in-flight and eval is non-terminal; only
                # outcome-bearing events feed novelty warnings.
                if ev.get("event") not in ("kept", "discarded", "note"):
                    continue
                text = " ".join([str(ev.get("run_id") or ""),
                                 json.dumps(ev.get("data") or {})])
                j = jaccard(toks, probe_tokens(text))
                if j >= 0.3:
                    ledger_hits.append({"source": str(led),
                                        "event": ev.get("event"),
                                        "run_id": ev.get("run_id"),
                                        "jaccard": round(j, 3)})
    runs_root = lp.omx_dir / "runs"
    if runs_root.is_dir():
        for lj in sorted(runs_root.glob("*/ledger.json")):
            try:
                led = json.loads(lj.read_text())
            except ValueError:
                continue
            for e in led.get("entries", []):
                j = jaccard(toks, probe_tokens(str(e.get("description") or "")))
                if j >= 0.3:
                    ledger_hits.append({"source": str(lj),
                                        "event": e.get("decision"),
                                        "run_id": lj.parent.name,
                                        "jaccard": round(j, 3)})
    out = {"wiki_hits": hits.get("matches", []), "similar_proposals": similar, "ledger_hits": ledger_hits}
    print(json.dumps(out))
    if similar:
        print(f"WARNING: probe family overlaps {len(similar)} past proposal(s) — "
              "check their outcome before re-trying it", file=sys.stderr)
    if ledger_hits:
        outcomes = {}
        for h in ledger_hits:
            outcomes[h["event"]] = outcomes.get(h["event"], 0) + 1
        print(f"WARNING: probe family appears in ledger history ({outcomes}) — "
              "check the recorded outcome before re-trying it", file=sys.stderr)
    return 0


def _cmd_queue_launch(args) -> int:
    """Queue the next training launch as a pending-approval artifact (B8).

    NEVER launches — writes runs/<run_id>/pending-launch.json and prints it.
    queued_at is the real clock, injected here (the core stays time-pure). With
    --cwd a git repo, records queued_commit = HEAD for launch provenance (#12,
    D-R4-6); a non-repo cwd or missing git warns and omits the sha."""
    import subprocess
    paths = OmxPaths(root=_resolved_root(args))
    now = clock.now_iso()
    # --- pre-launch wiki forcing gate (spec 4.a): REFUSE on an open HARD gate,
    # WARN on soft leads. Read-only; same enumerate_pages helper as `wiki list`, so
    # the gate can never drift from what the human sees. Empty/absent wiki -> passes;
    # a corrupt page is surfaced by lint, never blocks; an unknown status never blocks.
    acked = {_wiki_gc._norm_slug(s) for s in (args.ack_gate or [])}
    catalog = _wiki_query.enumerate_pages(paths)
    blocking = [pg for pg in catalog["pages"] if pg["status"] in _WIKI_BLOCKING_STATUSES]
    unacked = [pg for pg in blocking if pg["slug"] not in acked]
    if unacked:
        print(json.dumps({
            "refused": True,
            "open_gates": [{"slug": pg["slug"], "title": pg["title"],
                            "blocked_on": pg["blocked_on"]} for pg in unacked],
            "hint": ("resolve each via `omx wiki add --title <same> --status resolved`, "
                     "or rerun with `--ack-gate <slug>` per gate to launch over it"),
        }))
        return 2   # REFUSE: write nothing, nonzero rc
    soft = [pg for pg in catalog["pages"]
            if pg["status"] in _WIKI_STATUSES
            and pg["status"] not in _WIKI_BLOCKING_STATUSES
            and pg["status"] != "resolved"]
    open_leads = [pg["slug"] for pg in soft] or None
    acked_present = sorted(pg["slug"] for pg in blocking if pg["slug"] in acked) or None
    queued_commit = None
    if args.cwd:
        try:
            proc = subprocess.run(
                ["git", "-C", str(args.cwd), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=False)
            if proc.returncode == 0 and proc.stdout.strip():
                queued_commit = proc.stdout.strip()
            else:
                print(f"WARNING: could not record queued_commit (--cwd {args.cwd!r} "
                      "is not a git repo or has no HEAD)", file=sys.stderr)
        except (FileNotFoundError, OSError):
            print("WARNING: could not record queued_commit (git unavailable)",
                  file=sys.stderr)
    try:
        queue_pending_launch(
            paths, args.run_id,
            proposal_id=args.proposal_id, launch_delta=args.launch_delta,
            gpu_gate=args.gpu_gate, queued_at=now, queued_commit=queued_commit,
            open_leads=open_leads, acknowledged_gates=acked_present)
        print(json.dumps(read_pending_launch(paths, args.run_id)))
    except OmxError as e:
        raise SystemExit(str(e))
    # v0.8.0 campaign liveness: a queued launch is a `launched` event on the
    # campaign that planned this proposal. Advisory — never fails the queue.
    try:
        from omx_core.campaign import record_launched
        lres = record_launched(paths, args.proposal_id, args.run_id, now=now)
        if lres["status"] == "unplanned":
            print("WARNING: proposal not planned in any campaign — record "
                  "intent with `omx campaign-plan-add --id <group> "
                  f"--proposal-id {args.proposal_id}`", file=sys.stderr)
    except (OmxError, OSError, ValueError) as e:
        print(f"WARNING: campaign launched-event append failed: {e}",
              file=sys.stderr)
    if soft:
        print(f"WARNING: {len(soft)} open experiment lead(s) not resolved: "
              f"{', '.join(pg['slug'] for pg in soft)} "
              f"(carry into the plan or resolve; see `omx wiki list --status needs-experiment`)",
              file=sys.stderr)
    return 0


def _run_phase(paths, run_id, *, armed, now, deadline_override=None):
    """Derive (phase, lease, marker) for one run (spec 2.5/2.7). Pure read;
    corrupt marker -> phase 'unknown' (the caller warns). `armed` is the
    state's active_loop envelope (or None); `now` is the aware clock for the
    deadline check. `deadline_override` (when not None) is a caller-resolved
    deadline that WINS over the envelope's own deadline — the --run-id path
    passes the flag-resolved deadline (explicit --deadline > --max-runtime >
    envelope) so `phase`'s notion of 'passed' agrees with the response's
    deadline_passed field; the --all path passes None (envelope deadline)."""
    from omx_core.lock import read_run_lease
    marker = None
    unknown = False
    mpath = paths.loop_marker_json(run_id)
    if mpath.exists():
        try:
            marker = json.loads(mpath.read_text())
        except (ValueError, OSError):
            unknown = True
    lease = read_run_lease(paths, run_id)
    armed_here = bool(armed and armed.get("run_id") == run_id)
    passed = None
    effective_deadline = deadline_override or (armed.get("deadline") if armed_here else None)
    if effective_deadline:
        try:
            passed = deadline_passed(effective_deadline, now)
        except OmxError:
            passed = None
    if unknown:
        phase = "unknown"
    elif marker is not None:
        phase = "done"
    elif armed_here and passed is not True:
        phase = "running"
    elif armed_here and passed is True:
        phase = "died"
    elif lease is not None and not armed_here:
        phase = "died"
    else:
        phase = "idle"
    return phase, lease, marker


def _cmd_loop_status(args) -> int:
    """Report loop status. With --run-id: one run's deadline ceiling + pending
    launch + phase. With --all (#16): every run under runs/*/ as
    {run_id, phase, lease, marker, armed}. Claude-free.

    Deadline resolution order (--run-id path):
      1. --deadline (explicit ISO-8601) takes precedence.
      2. --max-runtime <seconds>: deadline = now + max_runtime via compute_deadline.
      3. Neither: deadline_passed is None (no ceiling check).
    """
    paths = OmxPaths(root=_resolved_root(args))
    now = args.now or clock.now_iso()
    from omx_core.state import load_state
    try:
        armed = load_state(paths).get("active_loop")
    except ValueError as e:
        raise SystemExit(f"state.json is corrupt: {e}")

    if args.all:
        runs_root = paths.omx_dir / "runs"
        rows = []
        run_ids = sorted(d.name for d in runs_root.iterdir()) if runs_root.is_dir() else []
        for rid in run_ids:
            try:
                phase, lease, marker = _run_phase(paths, rid, armed=armed, now=now)
            except Exception as e:
                print(f"WARNING: loop-status --all: run {rid!r} unreadable: {e}",
                      file=sys.stderr)
                rows.append({"run_id": rid, "phase": "unknown", "lease": None,
                             "marker": None, "armed": False})
                continue
            if phase == "unknown":
                print(f"WARNING: loop-status --all: run {rid!r} has a corrupt "
                      "marker (phase unknown)", file=sys.stderr)
            rows.append({
                "run_id": rid, "phase": phase,
                "lease": ({"session_id": lease.get("session_id"),
                           "armed_at": lease.get("armed_at")} if lease else None),
                "marker": ({"reason": marker.get("reason"),
                            "ended_at": marker.get("ended_at")} if marker else None),
                "armed": bool(armed and armed.get("run_id") == rid),
            })
        print(json.dumps({"runs": rows,
                          "armed_run": armed.get("run_id") if armed else None}))
        return 0

    # --run-id path (existing behavior + T3 phase)
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
    # pass the flag-resolved deadline (explicit --deadline > --max-runtime >
    # envelope) so phase's 'passed' agrees with the deadline_passed field above.
    phase, _lease, _marker = _run_phase(paths, args.run_id, armed=armed, now=now,
                                        deadline_override=deadline)
    print(json.dumps({
        "run_id": args.run_id,
        "now": now,
        "deadline": deadline,
        "deadline_passed": passed,
        "pending_launch": pending,
        "armed": armed,
        "phase": phase,
    }))
    return 0


def _cmd_loop_arm(args) -> int:
    """Arm the Stop-hook loop gate (spec 2.4). AWARE UTC clock via clock.now_iso()."""
    from omx_core.loop import arm_loop
    now = args.now or clock.now_iso()
    if args.now:
        # a naive --now would store a naive deadline that permanently trips the
        # gate's fail-open (deadline_passed raises on the mix, the gate swallows
        # it, the loop silently dies) — reject at the single arm entry point.
        try:
            parsed = datetime.fromisoformat(args.now)
        except ValueError:
            raise SystemExit(f"--now is not ISO-8601: {args.now!r}")
        if parsed.tzinfo is None:
            raise SystemExit(
                "--now must be timezone-AWARE UTC (e.g. 2026-07-11T10:00:00+00:00); "
                "a naive instant would write a naive deadline and silently fail the gate open.")
    stale_hours = None
    try:
        raw = load_profile_metrics(_resolved_root(args)).get("lock_stale_hours")
        if raw is not None:
            stale_hours = float(raw)
    except OmxError:
        pass  # no profile yet -> LOCK_STALE_HOURS default (D12: override slot)
    try:
        env = arm_loop(OmxPaths(root=_resolved_root(args)), run_id=args.run_id,
                       now_iso=now, max_runtime_s=args.max_runtime,
                       hard_cap=args.hard_cap, session_id=args.session_id,
                       stale_hours=stale_hours)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(env))
    return 0


def _cmd_loop_disarm(args) -> int:
    from omx_core.loop import disarm_loop
    try:
        out = disarm_loop(OmxPaths(root=_resolved_root(args)), reason=args.reason)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(out))
    return 0


def _cmd_loop_mark_done(args) -> int:
    """Write the loop-completion marker for an UNARMED single-pass flow (R4 #7).
    The armed path writes it automatically via disarm_loop; this verb covers a
    never-armed loop. AWARE UTC clock via clock.now_iso()."""
    from omx_core.loop import mark_loop_done
    now = clock.now_iso()
    try:
        marker = mark_loop_done(OmxPaths(root=_resolved_root(args)), args.run_id,
                                reason=args.reason, summary=args.summary or "", now_iso=now)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(marker))
    return 0


def _cmd_loop_health(args) -> int:
    """Circuit check over the run ledger (#8/#9). Thresholds come from the
    profile (plateau_discards / fault_streak, D12 override slots) with the
    named-constant fallbacks. Prints the health JSON; rc 2 when EITHER circuit
    is tripped (the authoritative stop path, D-R4-4). Loud-fails if the ledger
    is absent/corrupt (read_run_ledger)."""
    from omx_core.ledger import read_run_ledger
    from omx_core.loop import FAULT_STREAK_DEFAULT, PLATEAU_DISCARDS_DEFAULT, loop_health
    paths = OmxPaths(root=_resolved_root(args))
    plateau = PLATEAU_DISCARDS_DEFAULT
    fault = FAULT_STREAK_DEFAULT
    try:
        prof = load_profile_metrics(_resolved_root(args))
        plateau = int(prof.get("plateau_discards", plateau))
        fault = int(prof.get("fault_streak", fault))
    except OmxError:
        pass  # no profile yet -> named-constant defaults (D12: override slot)
    try:
        ledger = read_run_ledger(paths, args.run_id)
    except OmxError as e:
        raise SystemExit(str(e))
    health = loop_health(ledger, plateau_discards=plateau, fault_streak=fault)
    print(json.dumps(health))
    if health["plateau_tripped"] or health["fault_tripped"]:
        why = []
        if health["plateau_tripped"]:
            why.append(f"plateau: {health['consecutive_discards']} consecutive "
                       f"discards (>= {plateau}, knob plateau_discards)")
        if health["fault_tripped"]:
            why.append(f"fault_circuit: {health['consecutive_faults']} consecutive "
                       f"evaluator faults (>= {fault}, knob fault_streak)")
        raise SystemExit("loop-health tripped — " + "; ".join(why)
                         + ". Stop the loop (`omx loop-disarm --reason "
                         "plateau|fault_circuit`).")
    return 0


def _cmd_run_seed(args) -> int:
    """Seed the run ledger with the pre-experiment anchor (D-R4-2, wraps
    seed_ledger). Seeding is ONCE — loud-fail if the ledger already exists so a
    re-seed cannot silently reset the baseline_commit invariant.

    The once-check is a create-is-the-claim O_CREAT|O_EXCL placeholder write
    (mirrors lock.py's _write_lease idiom), not exists()-then-write: two
    concurrent run-seed calls for the same run_id can otherwise both pass the
    exists() check before either writes, and the loser's baseline_commit is
    silently overwritten with no error surfaced.

    A present-but-UNSEEDED ledger (baseline_commit is still None — the
    placeholder survived a kill between this claim and the seed_ledger call
    below) is NOT a completed seed: it is treated as absent so the retry can
    claim and actually seed it, instead of being permanently locked out."""
    import os

    from omx_core.ledger import _default_ledger, read_run_ledger, seed_ledger
    paths = OmxPaths(root=_resolved_root(args))
    target = paths.ledger_json(args.run_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        try:
            already_seeded = json.loads(target.read_text()).get("baseline_commit") is not None
        except (OSError, ValueError):
            already_seeded = True  # corrupt or race-vanished ledger: don't silently clobber it
        if already_seeded:
            raise SystemExit(
                f"ledger for run {args.run_id!r} already exists; seeding is once "
                "(re-seeding would reset the baseline_commit anchor)")
    else:
        try:
            fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            try:
                os.write(fd, json.dumps(_default_ledger(), indent=2, sort_keys=True).encode("utf-8"))
            finally:
                os.close(fd)
        except FileExistsError:
            # lost the create race to a concurrent claim; re-check its outcome
            # instead of assuming the winner finished seeding (see above).
            try:
                already_seeded = json.loads(target.read_text()).get("baseline_commit") is not None
            except (OSError, ValueError):
                already_seeded = False
            if already_seeded:
                raise SystemExit(
                    f"ledger for run {args.run_id!r} already exists; seeding is once "
                    "(re-seeding would reset the baseline_commit anchor)")
    try:
        # ponytail: the O_EXCL claim serializes only the placeholder write —
        # kill-recovery deliberately lets a lost-race caller fall through here,
        # so two concurrent seeds with CONFLICTING baselines last-write-win.
        # Wrap this call in the state_lock if concurrent conflicting seeds
        # ever become a real workload.
        seed_ledger(paths, args.run_id, baseline_commit=args.baseline_commit,
                    keep_policy=args.keep_policy)
        led = read_run_ledger(paths, args.run_id)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(led))
    return 0


def _is_ancestor(cwd, ancestor, descendant) -> bool | None:
    """True/False from `git merge-base --is-ancestor`; None when the check
    cannot run (not a git repo, unresolvable shas, no git). The run(check=False)
    idiom of wiki/gc.py: rc 0 = ancestor, rc 1 = not, other = cannot-tell."""
    import subprocess
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd), "merge-base", "--is-ancestor", ancestor, descendant],
            capture_output=True, text=True, check=False)
    except (FileNotFoundError, OSError):
        return None
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None  # 128 etc: bad sha / not a repo


def _cmd_run_record(args) -> int:
    """Record one iteration into the ledger (D-R4-2, wraps record_iteration),
    guarded by the run-lease assertion + the git-ancestry staleness check.

    Lease assertion (spec 2.3): a lease exists AND carries a session_id AND the
    caller passed --session-id AND they differ -> rc 2. Caller passed no
    --session-id while a lease exists -> stderr warning (unverifiable), proceed.
    No lease -> proceed silently (single-shot record outside a loop).

    Staleness (D-R4-6): with --cwd a git repo, base = last_kept_commit else
    baseline_commit must be an ANCESTOR of --candidate-commit; non-ancestor ->
    rc 2 (--no-staleness-check escapes); missing/non-repo cwd -> warn + skip."""
    from omx_core.ledger import read_run_ledger, record_iteration
    from omx_core.lock import read_run_lease
    paths = OmxPaths(root=_resolved_root(args))

    # (1) lease assertion
    lease = read_run_lease(paths, args.run_id)
    if lease is not None:
        owner = lease.get("session_id")
        if owner and args.session_id and owner != args.session_id:
            raise SystemExit(
                f"run {args.run_id!r} is owned by loop session {owner!r} "
                f"(armed {lease.get('armed_at')}); disarm it or pass the owning "
                "--session-id")
        if args.session_id is None:
            print(f"WARNING: a lease exists for run {args.run_id!r} but no "
                  "--session-id was passed — ownership unverifiable; proceeding",
                  file=sys.stderr)

    # (2) staleness check
    try:
        ledger = read_run_ledger(paths, args.run_id)
    except OmxError as e:
        raise SystemExit(str(e))
    if not args.no_staleness_check:
        if not args.cwd:
            print("WARNING: staleness check skipped (no --cwd)", file=sys.stderr)
        else:
            base = ledger.get("last_kept_commit") or ledger.get("baseline_commit")
            if not base:
                print("WARNING: staleness check skipped (no baseline/last-kept "
                      "commit in the ledger)", file=sys.stderr)
            else:
                anc = _is_ancestor(args.cwd, base, args.candidate_commit)
                if anc is None:
                    print(f"WARNING: staleness check skipped (--cwd {args.cwd!r} "
                          "is not a git repo or a sha is unresolvable)",
                          file=sys.stderr)
                elif anc is False:
                    raise SystemExit(
                        f"stale checkpoint: base {base!r} is NOT an ancestor of "
                        f"candidate {args.candidate_commit!r} — the candidate was "
                        "trained from a commit behind the kept line (grading a "
                        "phantom improvement). Pass --no-staleness-check to override.")

    # (3) embed the eval decision block (optional)
    evaluator = None
    if args.eval_json:
        try:
            eval_doc = json.loads(Path(args.eval_json).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise SystemExit(f"--eval-json unreadable or not JSON: {e}")
        # accept either a full `omx eval` doc (with a nested decision) or a bare
        # decision block; record_iteration wants a decision dict.
        decision = eval_doc.get("decision") if isinstance(eval_doc, dict) else None
        if decision is None:
            raise SystemExit("--eval-json must contain a 'decision' block "
                             "(run `omx eval --keep-policy ...`)")
        if (not isinstance(decision, dict) or "decision" not in decision
                or "decision_reason" not in decision):
            raise SystemExit("--eval-json 'decision' block missing required "
                             "'decision'/'decision_reason' field(s) (run "
                             "`omx eval --keep-policy ...`)")
        evaluator = decision
    else:
        # no eval doc: synthesize the minimal decision record_iteration needs.
        # decision_reason is a fixed marker (not the --description string) so a
        # ledger entry can tell a hand-entered verdict from an evaluator-derived
        # one at a glance (--description still lands in the entry's own field).
        evaluator = {"decision": args.decision, "keep": args.decision in ("keep", "bootstrap"),
                     "evaluator": None, "decision_reason": "manual record", "notes": []}

    try:
        record_iteration(paths, args.run_id, iteration=args.iteration,
                         decision=evaluator, candidate_checkpoint=args.candidate_checkpoint,
                         candidate_commit=args.candidate_commit, description=args.description)
        updated = read_run_ledger(paths, args.run_id)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(_finite_clean({
        "last_kept_commit": updated.get("last_kept_commit"),
        "last_kept_checkpoint": updated.get("last_kept_checkpoint"),
        "last_kept_score": updated.get("last_kept_score"),
        "entry": updated["entries"][-1] if updated.get("entries") else None,
    }), allow_nan=False))
    return 0


def _cmd_revert_config(args) -> int:
    """Two-phase config revert (#5, spec 2.8). Dry-run by default; mutation only
    with --i-approve-revert. Resolves the sha from the run ledger (--to
    baseline|last-kept|<sha>), builds the path-scoped allowlist (.omx/ under cwd
    + the resolved root tree when inside cwd), and prints the plan / applies it.
    Loud-fails: --cwd not a git repo, sha unresolvable, ledger absent."""
    from pathlib import Path as _Path

    from omx_core.ledger import read_run_ledger
    from omx_core.revert import apply_revert, plan_revert
    paths = OmxPaths(root=_resolved_root(args))
    try:
        ledger = read_run_ledger(paths, args.run_id)
    except OmxError as e:
        raise SystemExit(str(e))
    # resolve the target sha
    if args.to == "baseline":
        sha = ledger.get("baseline_commit")
    elif args.to == "last-kept":
        sha = ledger.get("last_kept_commit") or ledger.get("baseline_commit")
    else:
        sha = args.to  # explicit sha, verified inside plan_revert
    if not sha:
        raise SystemExit(
            f"cannot resolve --to {args.to!r} for run {args.run_id!r} "
            "(the ledger has no matching commit)")
    # path-scoped allowlist: .omx relative to cwd, plus the resolved root tree
    # when it lies inside cwd.
    protected = [".omx/"]
    cwd_res = _Path(args.cwd).resolve()
    root_res = _Path(_resolved_root(args)).resolve()
    try:
        rel = root_res.relative_to(cwd_res)
        if rel != _Path("."):  # root == cwd -> str(rel/".omx") is just ".omx/" (already in protected)
            protected.append(str(rel / ".omx") + "/")
    except ValueError:
        pass  # root is not inside cwd -> the ".omx/" prefix already covers cwd's tree
    try:
        plan = plan_revert(args.cwd, sha, protected)
    except OmxError as e:
        raise SystemExit(str(e))
    if not args.i_approve_revert:
        print(json.dumps({"dry_run": True, "target": sha, **plan}))
        return 0
    if not plan["would_revert"]:
        print(json.dumps({"dry_run": False, "target": sha, "reverted": []}))
        return 0
    try:
        apply_revert(args.cwd, sha, plan["would_revert"])
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps({"dry_run": False, "target": sha,
                      "reverted": plan["would_revert"]}))
    return 0


def _now_stamp() -> str:
    # local wall-clock; deterministic format YYYYMMDD-HHMMSS
    # BY DESIGN local-naive: scratch analysis-id naming, never compared (D-R5-5).
    import time
    return time.strftime("%Y%m%d-%H%M%S", time.localtime())


def _cmd_wiki_add(args) -> int:
    paths = OmxPaths(root=_resolved_root(args))
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
        floor = int(load_profile_metrics(_resolved_root(args)).get("wiki_quality_floor", floor))
    except OmxError:
        pass  # no profile yet — built-in floor (D12: override slot, generic default)
    score, reasons = score_page(content, tags, title=args.title)
    confidence = args.confidence
    forced = score < floor and confidence != "low"
    if forced:
        confidence = "low"
    try:
        res = _wiki_ingest.ingest_knowledge(
            paths, now=clock.now_iso_naive(), title=args.title, content=content,
            tags=tags, category=args.category, confidence=confidence,
            sources=[s.strip() for s in (args.sources or "").split(",") if s.strip()],
            quality_score=score, quality_reasons=reasons,
            status=args.status, blocked_on=args.blocked_on)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps({**res, "quality_score": score, "quality_forced_low": forced,
                      "quality_reasons": reasons}))
    return 0


def _cmd_wiki_delete(args) -> int:
    """Deprecation-as-runtime-redirect (#20, D-R5-2). There is no page delete:
    the wiki is append-merge (INV-2) and removal is the git-guarded gc path.
    ALWAYS loud-fails (rc 2) with a machine-readable JSON redirect naming the
    real path; deletes NOTHING. The positional slug + --root are accepted and
    ignored so a mistaken `omx wiki delete <slug>` reaches this redirect instead
    of dying in argparse with a generic 'invalid choice'."""
    root = _resolved_root(args)
    raise SystemExit(json.dumps({
        "error": "deprecated",
        "reason": "wiki is append-merge (INV-2); removal is git-guarded gc",
        "cli_replacement": (
            f"omx wiki gc --root {root} … then omx wiki gc-apply "
            f"--root {root} --proposal <approved-gc-proposal.md>"),
    }))


def _cmd_wiki_capture_session(args) -> int:
    """Write session-log stub pages from a report's [FINDING] blocks (#11, spec 3.7).

    Consumer boundary (#14): mirrors report-parse's integrity gate — capture is a
    report consumer too, and a tampered/ungated report must not seed durable wiki
    pages. mismatch/no-gates loud-fail (rc 2); unstamped (pre-0.2.0 legacy) only
    warns on stderr and still captures (spec 4 backward-compat; keeps loose test
    reports working)."""
    from omx_core.wiki.capture import capture_session
    report = Path(args.from_report)
    if not report.exists():
        raise SystemExit(f"report not found: {report}")
    v = _integrity.verify_report(str(report))
    if v["status"] in ("mismatch", "no-gates"):
        raise SystemExit(
            f"report integrity {v['status']} — refusing to capture a tampered/ungated "
            "report; re-enter exp-analyze (RE-analysis) so report-coverage re-stamps it")
    if v["status"] == "unstamped":
        print("WARNING: unstamped legacy report (pre-0.2.0); "
              "rc2 promotion earmarked for 0.3.0", file=sys.stderr)
    try:
        res = capture_session(
            OmxPaths(root=_resolved_root(args)), now=clock.now_iso_naive(),
            report_text=report.read_text(encoding="utf-8"),
            report_ref=str(report), run_id=args.run_id)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(res))
    return 0


def _cmd_wiki_capture_flush(args) -> int:
    """Session-end rescue: capture every ledger-recorded stamped report (spec 2.2).
    ALWAYS rc 0 — this runs at SessionEnd where a loud-fail helps nobody."""
    from omx_core.wiki.capture import flush_produced_reports
    res = flush_produced_reports(OmxPaths(root=_resolved_root(args)), now=clock.now_iso_naive())
    print(json.dumps(res))
    return 0


def _cmd_wiki_promote_recipe(args) -> int:
    """#15: promote a debugging page into .omx/recipes/ (reversible file
    creation; the 3-question gate + human approval happen in the skill)."""
    from omx_core.wiki.recipe import promote_recipe
    try:
        res = promote_recipe(OmxPaths(root=_resolved_root(args)), slug=args.slug,
                             now=clock.now_iso_naive(), name=args.name, force=args.force)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(res))
    return 0


def _cmd_wiki_query(args) -> int:
    paths = OmxPaths(root=_resolved_root(args))
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()] or None
    try:
        res = _wiki_query.query_wiki(
            paths, now=clock.now_iso_naive(), text=args.text, tags=tags,
            category=args.category, limit=args.limit)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(res))
    return 0


def _cmd_wiki_lint(args) -> int:
    paths = OmxPaths(root=_resolved_root(args))
    from omx_core.wiki.quality import QUALITY_FLOOR
    floor = QUALITY_FLOOR
    try:
        floor = int(load_profile_metrics(_resolved_root(args)).get("wiki_quality_floor", floor))
    except OmxError:
        pass  # no profile yet — built-in floor (D12: override slot, generic default)
    try:
        res = _wiki_lint.lint_wiki(
            paths, now=clock.now_iso_naive(), stale_days=args.stale_days,
            max_page_size=args.max_page_size, quality_floor=floor)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(res))
    return 0


def _cmd_wiki_list(args) -> int:
    paths = OmxPaths(root=_resolved_root(args))
    # --status enumerates the backlog by construction (keyword-independent); the same
    # helper backs the queue-launch gate so the two views can never drift.
    print(json.dumps(_wiki_query.enumerate_pages(paths, status=args.status)))
    return 0


def _cmd_wiki_read(args) -> int:
    """Print one wiki page's FULL text by slug (query=search, read=full text;
    symmetric with list/add). Default emits the '---' frontmatter block + body
    via serialize_page; --no-frontmatter emits only the body. An absent slug
    loud-fails (SystemExit) rather than printing nothing, so callers can tell
    'page absent' from 'page empty'."""
    paths = OmxPaths(root=_resolved_root(args))
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


def _cmd_wiki_sync_profile(args) -> int:
    from omx_core.wiki.sync import sync_profile_page
    try:
        res = sync_profile_page(OmxPaths(root=_resolved_root(args)), now=clock.now_iso_naive())
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(res))
    return 0


def _cmd_wiki_gc(args) -> int:
    """Read-only gc diagnosis: lint result + page metadata, as one JSON object for
    the skill to read. Touches nothing (the skill judges, gc-apply executes)."""
    paths = OmxPaths(root=_resolved_root(args))
    try:
        lint_res = _wiki_lint.lint_wiki(paths, now=clock.now_iso_naive(),
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
    paths = OmxPaths(root=_resolved_root(args))
    try:
        plan = _wiki_gc.parse_gc_proposal(proposal.read_text(encoding="utf-8"))
        res = _wiki_gc.apply_gc(paths, plan, now=clock.now_iso_naive(), repo_root=_resolved_root(args))
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(res))
    return 0


def _cmd_clean(args) -> int:
    """#22 -- review-gated cleanup: dry-run by default; --apply trashes, never rm."""
    from omx_core.clean import apply_sweep, classify, purge_trash
    paths = OmxPaths(root=_resolved_root(args))
    try:
        if args.purge_trash:
            if not args.i_understand_permanent:
                raise SystemExit(
                    "--purge-trash requires --i-understand-permanent (the second "
                    "explicit confirm; this deletes the trash for real)")
            print(json.dumps(purge_trash(paths)))
            return 0
        days = None
        if args.older_than is not None:
            if not args.older_than.endswith("d") or not args.older_than[:-1].isdigit():
                raise SystemExit("--older-than takes <N>d (days), e.g. 7d")
            days = int(args.older_than[:-1])
        entries = classify(paths, scope=args.scope, session_id=args.session_id,
                           older_than_days=days)
    except OmxError as e:
        raise SystemExit(str(e))
    view = [{k: e[k] for k in ("path", "bytes", "reason")} for e in entries]
    if not args.apply:
        print(json.dumps({"dry_run": True, "scope": args.scope, "sweep": view,
                          "total_bytes": sum(e["bytes"] for e in view)}))
        return 0
    # BY DESIGN local-naive: .trash timestamp NAME, never compared (D-R5-5).
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    res = apply_sweep(paths, entries, trash_ts=ts)
    print(json.dumps({"dry_run": False, "scope": args.scope, **res}))
    return 0


def _cmd_campaign_init(args) -> int:
    from omx_core.campaign import init_campaign
    paths = OmxPaths(root=_resolved_root(args))
    extra = None
    if args.plan is not None:
        try:
            extra = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise SystemExit(f"--plan file unreadable or not JSON: {e}")
        if not isinstance(extra, dict):
            raise SystemExit("--plan file must contain a JSON object")
    try:
        plan = init_campaign(paths, args.id, now=clock.now_iso(), goal=args.goal,
                             baseline_run_id=args.baseline_run,
                             predecessor=args.predecessor, extra=extra)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(plan))
    return 0


def _cmd_campaign_log(args) -> int:
    from omx_core.campaign import append_event
    paths = OmxPaths(root=_resolved_root(args))
    data = None
    if args.data is not None:
        try:
            data = json.loads(args.data)
        except ValueError as e:
            raise SystemExit(f"--data must parse as a JSON object: {e}")
        if not isinstance(data, dict):
            raise SystemExit("--data must parse as a JSON object (got a non-object)")
    try:
        rec = append_event(paths, args.id, now=clock.now_iso(), event=args.event,
                           run_id=args.run, session_id=args.session_id, data=data)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(rec))
    return 0


def _cmd_campaign_status(args) -> int:
    from omx_core.campaign import campaign_status
    try:
        print(json.dumps(campaign_status(OmxPaths(root=_resolved_root(args)), args.id)))
    except OmxError as e:
        raise SystemExit(str(e))
    return 0


def _cmd_program_init(args) -> int:
    from omx_core.campaign import init_program
    campaigns = [c.strip() for c in args.campaigns.split(",") if c.strip()]
    try:
        header = init_program(OmxPaths(root=_resolved_root(args)), args.id,
                              campaigns, now=clock.now_iso())
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(header))
    print("note: PLAN.md is not generated — move the program narrative into "
          "place with git mv (see README: program layer)", file=sys.stderr)
    return 0


def _cmd_program_status(args) -> int:
    from omx_core.campaign import program_status
    try:
        print(json.dumps(program_status(OmxPaths(root=_resolved_root(args)),
                                        args.id)))
    except OmxError as e:
        raise SystemExit(str(e))
    return 0


def _cmd_campaign_list(args) -> int:
    from omx_core.campaign import list_campaigns
    print(json.dumps({"campaigns": list_campaigns(OmxPaths(root=_resolved_root(args)))}))
    return 0


def _cmd_campaign_plan_add(args) -> int:
    from omx_core.campaign import plan_add
    paths = OmxPaths(root=_resolved_root(args))
    try:
        plan = plan_add(paths, args.id, proposal_id=args.proposal_id,
                        summary=args.summary, label=args.label, now=clock.now_iso())
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(plan))
    return 0


def _cmd_campaign_drift(args) -> int:
    from omx_core.campaign import adopt_drift, campaign_drift
    from omx_core.tree import load_tree_schema
    root = _resolved_root(args)
    paths = OmxPaths(root=root)
    try:
        schema = load_tree_schema(paths.tree_yaml())
        if args.adopt:
            print(json.dumps(adopt_drift(paths, schema, Path(root),
                                         now=clock.now_iso())))
        else:
            print(json.dumps(campaign_drift(paths, schema, Path(root))))
    except OmxError as e:
        raise SystemExit(str(e))
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

    pcc = sub.add_parser("card-check",
                         help="cross-repo card-currency guard: card.version == "
                              "plugin.json.version + every plugin skill mentioned "
                              "in the card (run at release time; D-R5-4)")
    pcc.add_argument("--card", default=None,
                     help="omha card path (default: $OMX_CARD_PATH else "
                          "~/.claude/plugins/marketplaces/heroacademia/cards/omx.json)")
    pcc.add_argument("--plugin-root", default=None, dest="plugin_root",
                     help="plugin dir holding .claude-plugin/plugin.json "
                          "(default: $CLAUDE_PLUGIN_ROOT else the repo-root fallback)")
    pcc.set_defaults(func=_cmd_card_check)

    pe = sub.add_parser("eval", help="run an evaluator command, parse {pass,score?} (Claude-free)")
    pe.add_argument("--command", required=True, help="shell command; LAST stdout line must be the JSON verdict")
    pe.add_argument("--cwd", default=None, help="working dir for the command (default: cwd)")
    pe.add_argument("--timeout", type=int, default=600, help="seconds before the evaluator is killed (status=error)")
    pe.add_argument("--keep-policy", default=None, dest="keep_policy",
                    help="pass_only | score_improvement; when set, embeds a decide_outcome block")
    pe.add_argument("--last-kept-score", type=float, default=None, dest="last_kept_score",
                    help="prior baseline score for score_improvement comparison")
    pe.add_argument("--seeds", type=int, default=None,
                    help="opt-in: run --command this many times (N>=2) and gate "
                         "keep on mean±std across seeds instead of one score "
                         "(decide_outcome's SEED_GATE_K significance gate)")
    pe.add_argument("--root", default=None, help="optional .omx anchor; enables the profile seal preflight (#0)")
    pe.set_defaults(func=_cmd_eval)

    psl = sub.add_parser("profile-seal",
                         help="seal .omx/profile/{evaluator.sh,launch.sh} sha256 at approval time (#0)")
    psl.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    psl.set_defaults(func=_cmd_profile_seal)

    pp = sub.add_parser("plot", help="render a candidate curve PNG into scratch (Claude-free IO)")
    pp.add_argument("--root", default=None, help="anchor dir under which .omx/ lives; default: #13 ladder")
    pp.add_argument("--session-id", required=True, dest="session_id")
    pp.add_argument("--path", required=True, help="series source (npz/TB/wandb)")
    pp.add_argument("--format", required=True)
    pp.add_argument("--series", required=True, help="series key within the source")
    pp.add_argument("--metric", required=True, help="metric token (output filename field)")
    pp.add_argument("--view", required=True, help="view token (output filename field)")
    _add_ingest_bounds(pp, with_root=False)
    pp.set_defaults(func=_cmd_plot)

    pm = sub.add_parser("promote-plots", help="B3: move report-referenced PNGs scratch->permanent")
    pm.add_argument("--root", default=None, help="anchor dir under which .omx/ lives; default: #13 ladder")
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
    pn.add_argument("--root", default=None, help="anchor dir under which .omx/ lives (design H4); default: #13 ladder")
    pn.add_argument("--profile-name", default="isaaclab", dest="profile_name",
                    help="committed reference profile to seed evaluator.sh from")
    pn.add_argument("--metrics-json", default=None, dest="metrics_json",
                    help="metrics.yaml content as a JSON object; omitted = built-in defaults")
    pn.add_argument("--force", action="store_true", help="overwrite an existing profile")
    pn.set_defaults(func=_cmd_init)

    ptc = sub.add_parser("tree-codify",
                         help="infer .omx/profile/tree.yaml from an existing tree "
                              "(census-based, pending approval)")
    ptc.add_argument("--root", default=None, help="anchor; default: #13 ladder")
    ptc.add_argument("--index-root", default=None, dest="index_root",
                     help="index tree root relative to the anchor (default: experiments)")
    ptc.add_argument("--data-root", default=None, dest="data_root",
                     help="data tree root override (default: inferred from pointers)")
    ptc.add_argument("--force", action="store_true",
                     help="regenerate over an existing tree.yaml")
    ptc.set_defaults(func=_cmd_tree_codify)

    pta = sub.add_parser("tree-audit",
                         help="validate the output trees against tree.yaml "
                              "(report-only; --strict escalates errors to rc 2)")
    pta.add_argument("--root", default=None, help="anchor; default: #13 ladder")
    pta.add_argument("--strict", action="store_true",
                     help="rc 2 when any error-severity violation is found")
    pta.set_defaults(func=_cmd_tree_audit)

    pts = sub.add_parser("tree-scaffold",
                         help="mint a run skeleton or an eval leaf per tree.yaml "
                              "(refuses existing leaves — F4 guard; never launches)")
    pts.add_argument("--root", default=None, help="anchor; default: #13 ladder")
    pts.add_argument("--run-id", default=None, dest="run_id")
    pts.add_argument("--under", default=None,
                     help="'/'-joined level values, e.g. fw/exp_a/camp_a")
    pts.add_argument("--data-dir", default=None, dest="data_dir",
                     help="training log dir the data_pointer symlink targets")
    pts.add_argument("--eval-for", default=None, dest="eval_for",
                     help="run spec (path or exact leaf) to mint an eval leaf under")
    pts.add_argument("--mode", default=None, help="eval mode (must be in eval_modes)")
    pts.add_argument("--ts", default=None, help="explicit timestamp (tests)")
    pts.set_defaults(func=_cmd_tree_scaffold)

    ptl = sub.add_parser("tree-alias",
                         help="create/re-point a DECLARED alias symlink to a run "
                              "(atomic; refuses undeclared names and dangling targets)")
    ptl.add_argument("--root", default=None, help="anchor; default: #13 ladder")
    ptl.add_argument("--name", default=None)
    ptl.add_argument("--run", default=None, help="run spec (path or exact leaf)")
    ptl.add_argument("--scope-path", default=None, dest="scope_path",
                     help="explicit alias location (required when the scope "
                          "level is optional and absent on the target)")
    ptl.add_argument("--list", action="store_true")
    ptl.set_defaults(func=_cmd_tree_alias)

    pti = sub.add_parser("tree-index",
                         help="regenerate the generated INDEX.md at the index root "
                              "(marker-guarded; --check reports staleness as rc 2)")
    pti.add_argument("--root", default=None, help="anchor; default: #13 ladder")
    pti.add_argument("--check", action="store_true")
    pti.add_argument("--adopt", action="store_true",
                     help="overwrite an unmarked (hand-written) INDEX.md")
    pti.set_defaults(func=_cmd_tree_index)

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
    prc.add_argument("--root", default=None, help="workspace root holding .omx/profile/metrics.yaml; default: #13 ladder")
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

    ppl = sub.add_parser("proposal-lint",
                         help="gate exp-design proposals: H1/H2 discriminating predictions + evidence + refs (loud-fail)")
    ppl.add_argument("--path", required=True, help="path to a proposals/<id>.md")
    ppl.set_defaults(func=_cmd_proposal_lint)

    ppn = sub.add_parser("probe-novelty",
                         help="warn-only: was this probe family already tried? (wiki + past proposals)")
    ppn.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    ppn.add_argument("--path", default=None, help="proposal path (canonical flag)")
    ppn.add_argument("--proposal", default=None, help="alias of --path (deprecated)")
    ppn.add_argument("--proposals-dir", default=None, dest="proposals_dir",
                     help="dir of past proposals/<id>.md to compare against")
    ppn.set_defaults(func=_cmd_probe_novelty)

    pq = sub.add_parser("queue-launch",
                        help="queue the next training launch as pending-approval (B8; never fires)")
    pq.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    pq.add_argument("--run-id", required=True)
    pq.add_argument("--proposal-id", required=True)
    pq.add_argument("--launch-delta", required=True)
    pq.add_argument("--gpu-gate", required=True)
    pq.add_argument("--cwd", default=None,
                    help="training git repo; when given, records queued_commit = HEAD "
                         "for launch provenance (#12)")
    pq.add_argument("--ack-gate", action="append", default=None, dest="ack_gate",
                    metavar="SLUG",
                    help="acknowledge an open HARD wiki gate (status needs-apply-before-retrain) "
                         "and launch over it; repeatable, per-slug (no blanket override). The "
                         "acked slug is recorded in the pending-launch artifact.")
    pq.set_defaults(func=_cmd_queue_launch)

    pl = sub.add_parser("loop-status",
                        help="report deadline-ceiling + pending-launch + phase as JSON; "
                             "--all reports every run (Claude-free)")
    pl.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    _pl_grp = pl.add_mutually_exclusive_group(required=True)
    _pl_grp.add_argument("--run-id", default=None, help="report one run")
    _pl_grp.add_argument("--all", action="store_true",
                         help="report every run under runs/*/ (#16)")
    pl.add_argument("--deadline", default=None,
                    help="ISO-8601 deadline; omit to skip the ceiling check")
    pl.add_argument("--now", default=None,
                    help="ISO-8601 now (defaults to the real clock; pass for tests)")
    pl.add_argument("--max-runtime", type=int, default=None, dest="max_runtime",
                    help="seconds; when --deadline is omitted, the deadline is "
                         "computed as now + max-runtime (the leaving-work ceiling)")
    pl.set_defaults(func=_cmd_loop_status)

    pla = sub.add_parser("loop-arm",
                         help="arm the Stop-hook loop gate: one loop per root, "
                              "mandatory --max-runtime self-expiry (spec 2.4)")
    pla.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    pla.add_argument("--run-id", required=True, dest="run_id")
    pla.add_argument("--max-runtime", required=True, type=int, dest="max_runtime",
                     help="seconds until the gate self-expires (MANDATORY)")
    pla.add_argument("--hard-cap", type=int, default=50, dest="hard_cap",
                     help="max blocked stops before the gate self-disarms (default 50)")
    pla.add_argument("--now", default=None,
                     help="ISO-8601 aware instant for deterministic tests; default: real UTC clock")
    pla.add_argument("--session-id", default=None, dest="session_id",
                     help="omx session id claiming the run lease (the value "
                          "`omx session-id` resolves); the lease guards ownership")
    pla.set_defaults(func=_cmd_loop_arm)

    pld = sub.add_parser("loop-disarm",
                         help="clear the armed loop gate (idempotent; the standing exit)")
    pld.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    pld.add_argument("--reason", default="cancel",
                     choices=["done", "deadline", "cancel", "hard_cap",
                              "plateau", "fault_circuit", "ledger_corrupt"])
    pld.set_defaults(func=_cmd_loop_disarm)

    plm = sub.add_parser("loop-mark-done",
                         help="write the loop-completion marker for an UNARMED "
                              "single-pass flow (armed loops mark on disarm)")
    plm.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    plm.add_argument("--run-id", required=True, dest="run_id")
    # single-pass marker vocabulary (spec 2.5) — deliberately narrower than the
    # seven-value disarm-reason set (D-R4-11): hard_cap/plateau/fault_circuit only
    # arise from armed-gate flows, which mark via disarm_loop, never this verb.
    plm.add_argument("--reason", default="done",
                     choices=["done", "deadline", "cancel", "error"])
    plm.add_argument("--summary", default=None, help="one-line summary (e.g. 'iteration 3')")
    plm.set_defaults(func=_cmd_loop_mark_done)

    plh = sub.add_parser("loop-health",
                         help="circuit check over the run ledger (#8/#9): rc 2 "
                              "when plateau/fault streak trips (authoritative stop)")
    plh.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    plh.add_argument("--run-id", required=True, dest="run_id")
    plh.set_defaults(func=_cmd_loop_health)

    prs2 = sub.add_parser("run-seed",
                          help="seed the run ledger with the baseline anchor "
                               "(D-R4-2; once — loud-fail if it exists)")
    prs2.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    prs2.add_argument("--run-id", required=True, dest="run_id")
    prs2.add_argument("--baseline-commit", required=True, dest="baseline_commit")
    prs2.add_argument("--keep-policy", required=True, dest="keep_policy",
                      choices=["pass_only", "score_improvement"])
    prs2.set_defaults(func=_cmd_run_seed)

    prc2 = sub.add_parser("run-record",
                          help="record one loop iteration into the ledger "
                               "(D-R4-2; lease-asserted + ancestry-staleness-checked)")
    prc2.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    prc2.add_argument("--run-id", required=True, dest="run_id")
    prc2.add_argument("--iteration", required=True, type=int)
    prc2.add_argument("--decision", required=True,
                      choices=["keep", "discard", "ambiguous", "bootstrap"])
    prc2.add_argument("--candidate-checkpoint", required=True, dest="candidate_checkpoint")
    prc2.add_argument("--candidate-commit", required=True, dest="candidate_commit")
    prc2.add_argument("--description", required=True)
    prc2.add_argument("--session-id", default=None, dest="session_id",
                      help="assert loop-lease ownership by session id (warns if omitted while a lease exists)")
    prc2.add_argument("--cwd", default=None,
                      help="project git repo for the ancestry staleness check")
    prc2.add_argument("--eval-json", default=None, dest="eval_json",
                      help="path to a saved `omx eval` doc; its decision block is embedded")
    prc2.add_argument("--no-staleness-check", action="store_true", dest="no_staleness_check",
                      help="skip the git-ancestry staleness check (documented escape)")
    prc2.set_defaults(func=_cmd_run_record)

    prv2 = sub.add_parser("revert-config",
                          help="two-phase config revert to a run's baseline/last-kept "
                               "commit (#5; dry-run default, --i-approve-revert applies)")
    prv2.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    prv2.add_argument("--cwd", required=True, help="the project git repo to revert in")
    prv2.add_argument("--run-id", required=True, dest="run_id")
    prv2.add_argument("--to", default="baseline",
                      help="baseline | last-kept | <sha> (default: baseline)")
    prv2.add_argument("--i-approve-revert", action="store_true", dest="i_approve_revert",
                      help="APPLY the revert (git checkout); without this it is dry-run only")
    prv2.set_defaults(func=_cmd_revert_config)

    pw = sub.add_parser("wiki", help="workspace knowledge wiki (keyword-indexed, no embeddings)")
    wsub = pw.add_subparsers(dest="wiki_cmd", required=True)

    pwa = wsub.add_parser("add", help="add/merge a page, OR --from-report to extract candidates")
    pwa.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    pwa.add_argument("--title", default=None)
    pwa.add_argument("--category", default=None)
    pwa.add_argument("--tags", default=None, help="comma-separated")
    pwa.add_argument("--confidence", default=None, choices=["high", "medium", "low"])
    pwa.add_argument("--content", default=None, help="content text, or '-' for stdin")
    pwa.add_argument("--sources", default=None, help="comma-separated source ids")
    pwa.add_argument("--from-report", default=None, dest="from_report",
                     help="extract-only: print [FINDING] candidates from a report.md, write nothing")
    pwa.add_argument("--status", default=None, choices=list(_WIKI_STATUSES),
                     help="actionable status (absent = not actionable); enumerated by `wiki list --status <value>`")
    pwa.add_argument("--blocked-on", default=None, dest="blocked_on",
                     help="optional annotation; a blocked lead KEEPS its actionable status")
    pwa.set_defaults(func=_cmd_wiki_add)

    pwc = wsub.add_parser("capture-session",
                          help="write every report [FINDING] as a low-confidence session-log stub page (#11)")
    pwc.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    pwc.add_argument("--from-report", required=True, dest="from_report")
    pwc.add_argument("--run-id", default=None, dest="run_id",
                     help="optional run id added as a tag")
    pwc.set_defaults(func=_cmd_wiki_capture_session)

    pwf = wsub.add_parser("capture-flush",
                          help="capture ALL ledger-recorded stamped reports as "
                               "session-log stubs, then truncate the ledger "
                               "(SessionEnd rescue; always rc 0)")
    pwf.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    pwf.set_defaults(func=_cmd_wiki_capture_flush)

    pwp = wsub.add_parser("promote-recipe",
                          help="#15: promote a high-value debugging page into "
                               ".omx/recipes/<name>.md (human-gated in the skill)")
    pwp.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    pwp.add_argument("--slug", required=True, help="source wiki page (category MUST be debugging)")
    pwp.add_argument("--name", default=None, help="recipe filename (default: the slug)")
    pwp.add_argument("--force", action="store_true", help="overwrite an existing recipe")
    pwp.set_defaults(func=_cmd_wiki_promote_recipe)

    pwq = wsub.add_parser("query", help="keyword + tag search (tag>title>content, CJK-aware)")
    pwq.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    pwq.add_argument("text", help="query text")
    pwq.add_argument("--tags", default=None, help="comma-separated tag filter")
    pwq.add_argument("--category", default=None)
    pwq.add_argument("--limit", type=int, default=20)
    pwq.set_defaults(func=_cmd_wiki_query)

    pwl = wsub.add_parser("lint", help="audit pages (orphan/stale/broken-ref/oversized), report-only")
    pwl.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    pwl.add_argument("--stale-days", type=int, default=30, dest="stale_days")
    pwl.add_argument("--max-page-size", type=int, default=10240, dest="max_page_size")
    pwl.set_defaults(func=_cmd_wiki_lint)

    pwls = wsub.add_parser("list", help="catalog of pages (slug/title/category/status); "
                                        "--status enumerates the backlog by construction")
    pwls.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    pwls.add_argument("--status", default=None, choices=list(_WIKI_STATUSES),
                      help="filter to one actionable status (keyword-independent backlog)")
    pwls.set_defaults(func=_cmd_wiki_list)

    pwr = wsub.add_parser("read", help="print one page's full text by slug (loud-fail if absent)")
    pwr.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    pwr.add_argument("--slug", required=True, help="page slug (with or without '.md')")
    pwr.add_argument("--no-frontmatter", action="store_true", dest="no_frontmatter",
                     help="emit only the body, omitting the '---' frontmatter block")
    pwr.set_defaults(func=_cmd_wiki_read)

    pws = wsub.add_parser("sync-profile",
                          help="regenerate the reserved profile.md projection from .omx/profile/ (#17)")
    pws.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    pws.set_defaults(func=_cmd_wiki_sync_profile)

    pwg = wsub.add_parser("gc", help="read-only gc diagnosis (lint + page metadata as JSON); "
                                     "first step of the delete/merge path")
    pwg.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    pwg.add_argument("--stale-days", type=int, default=30, dest="stale_days")
    pwg.add_argument("--max-page-size", type=int, default=10240, dest="max_page_size")
    pwg.set_defaults(func=_cmd_wiki_gc)

    pwga = wsub.add_parser("gc-apply",
                           help="apply an approved wiki-gc proposal (two-phase, git-guarded) -- "
                                "THIS is how you delete/merge pages; there is no separate 'delete' "
                                "subcommand by design (add is append-merge, removal is git-guarded gc)")
    pwga.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    pwga.add_argument("--proposal", required=True, help="path to the approved wiki-gc proposal .md")
    pwga.set_defaults(func=_cmd_wiki_gc_apply)

    pwd = wsub.add_parser("delete",
                          help="DEPRECATED: there is no page delete (append-merge, "
                               "INV-2) — always errors with the gc/gc-apply redirect")
    pwd.add_argument("--root", default=None, help="optional .omx anchor; default: #13 ladder")
    pwd.add_argument("slug", nargs="?", default=None,
                     help="ignored — accepted only so a mistaken call reaches the redirect")
    pwd.set_defaults(func=_cmd_wiki_delete)

    pcl = sub.add_parser("clean",
                         help="review-gated .omx cleanup: classify -> dry-run -> "
                              "--apply moves to .omx/.trash (never rm; output "
                              "trees are structurally unreachable)")
    pcl.add_argument("--root", default=None, help="anchor; default: #13 ladder")
    pcl.add_argument("--scope", default="session", choices=("session", "run", "all"))
    pcl.add_argument("--session-id", default=None, dest="session_id")
    pcl.add_argument("--older-than", default=None, dest="older_than",
                     help="only sweep candidates older than <N>d (dir mtime)")
    pcl.add_argument("--apply", action="store_true")
    pcl.add_argument("--purge-trash", action="store_true", dest="purge_trash")
    pcl.add_argument("--i-understand-permanent", action="store_true",
                     dest="i_understand_permanent")
    pcl.set_defaults(func=_cmd_clean)

    pci = sub.add_parser("campaign-init", help="create .omx/campaigns/<id>/ "
                         "(plan.json + empty ledger); id = the tree's group segment")
    pci.add_argument("--root", default=None)
    pci.add_argument("--id", required=True)
    pci.add_argument("--goal", default=None)
    pci.add_argument("--baseline-run", default=None, dest="baseline_run")
    pci.add_argument("--predecessor", default=None,
                     help="campaign this one continues (recorded link only)")
    pci.add_argument("--plan", default=None, help="optional JSON file merged into plan.json")
    pci.set_defaults(func=_cmd_campaign_init)

    pcg = sub.add_parser("campaign-log", help="append one event to the campaign ledger")
    pcg.add_argument("--root", default=None)
    pcg.add_argument("--id", required=True)
    pcg.add_argument("--event", required=True,
                     choices=("launched", "kept", "discarded", "eval", "note"))
    pcg.add_argument("--run", default=None)
    pcg.add_argument("--data", default=None, help="JSON object payload")
    pcg.add_argument("--session-id", default=None, dest="session_id")
    pcg.set_defaults(func=_cmd_campaign_log)

    pcs = sub.add_parser("campaign-status", help="aggregate one campaign's ledger")
    pcs.add_argument("--root", default=None)
    pcs.add_argument("--id", required=True)
    pcs.set_defaults(func=_cmd_campaign_status)

    pcll = sub.add_parser("campaign-list", help="list campaigns with event counts")
    pcll.add_argument("--root", default=None)
    pcll.set_defaults(func=_cmd_campaign_list)

    pcp = sub.add_parser("campaign-plan-add",
                         help="record a planned proposal into plan.json's `planned` "
                              "list (intent; status is derived at read time)")
    pcp.add_argument("--root", default=None)
    pcp.add_argument("--id", required=True)
    pcp.add_argument("--proposal-id", required=True, dest="proposal_id")
    pcp.add_argument("--summary", default=None)
    pcp.add_argument("--label", default=None,
                     help="short human label (e.g. C2) — the handle prose uses")
    pcp.set_defaults(func=_cmd_campaign_plan_add)

    pcd = sub.add_parser("campaign-drift",
                         help="compare runs-on-disk against .omx/campaigns/ "
                              "(report-only; --adopt = one-shot remediation)")
    pcd.add_argument("--root", default=None)
    pcd.add_argument("--adopt", action="store_true",
                     help="init missing campaigns + note-adopt empty ledgers")
    pcd.set_defaults(func=_cmd_campaign_drift)

    ppi = sub.add_parser("program-init", help="create .omx/programs/<id>/ "
                         "(program.json header; PLAN.md arrives via git mv)")
    ppi.add_argument("--id", required=True)
    ppi.add_argument("--campaigns", required=True,
                     help="comma-separated member campaign ids")
    ppi.add_argument("--root", default=None)
    ppi.set_defaults(func=_cmd_program_init)

    pps = sub.add_parser("program-status", help="aggregate member campaigns "
                         "into one cross-group program view")
    pps.add_argument("--id", default=None)
    pps.add_argument("--root", default=None)
    pps.set_defaults(func=_cmd_program_status)

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
