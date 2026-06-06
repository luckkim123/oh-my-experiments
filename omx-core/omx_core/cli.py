"""omx_core.cli — the `omx` command (Claude-free verbs: ingest, reduce, session-id).

These verbs are pure Python so they are unit-testable from Bash with no Claude
or Isaac dependency. Skills (builds #3-#6) shell out to these.
"""
import argparse
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
from omx_core.omx_paths import OmxError, OmxPaths, validate_token, resolve_session_id
from datetime import datetime, timezone

from omx_core.loop import queue_pending_launch, read_pending_launch, deadline_passed, compute_deadline
from omx_core.profile import bootstrap_profile, default_metrics
from omx_core.report import parse_findings
from omx_core.coverage import check_coverage
from omx_core.profile import load_profile_metrics
from omx_core.wiki import ingest as _wiki_ingest, query as _wiki_query, lint as _wiki_lint, storage as _wiki_storage


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


def _ingest(path, fmt):
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
    return _ADAPTERS[fmt]().ingest(path)


def _cmd_ingest(args) -> int:
    res = _ingest(args.path, args.format)
    print(json.dumps({
        "format": res.meta.get("format"),
        "source": res.meta.get("source"),
        "n_summary": len(res.summary),
        "n_series": len(res.series),
    }))
    return 0


def _cmd_reduce_summarize(args) -> int:
    res = _ingest(args.path, args.format)
    df = to_dataframe(res.summary)
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
    res = _ingest(args.path, args.format)
    try:
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


def _cmd_eval(args) -> int:
    """Run an evaluator command, print its contract record (+ optional decision).

    rc 0 when the evaluator produced a graded verdict (status pass|fail);
    rc 1 when the evaluator itself errored (status error) — so Bash callers can
    tell 'graded' from 'broke'. With --keep-policy, also runs decide_outcome and
    embeds a 'decision' block (B5 coupling visible from the CLI).
    """
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


def _cmd_plot(args) -> int:
    """Render ONE candidate curve from a series source into scratch/<sid>/plots/.

    Claude-free: the skill picks WHICH series/metric/view; this verb does the
    matplotlib + scratch-path IO (design D8). Output filename = <metric>__<view>.png.
    """
    res = _ingest(args.path, args.format)
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
    on success; rc 2 (SystemExit) on a missing file or a malformed tag run."""
    path = args.path
    if not os.path.exists(path):
        raise SystemExit(f"report not found: {path}")
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
    }))
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
    try:
        profile = load_profile_metrics(args.root)
        res = check_coverage(text, profile)
    except OmxError as e:
        raise SystemExit(str(e))
    out = {
        "ok": res.ok,
        "missing_groups": res.missing_groups,
        "engine_cited": res.engine_cited,
        "checked_groups": res.checked_groups,
        "markers_declared": res.markers_declared,
    }
    print(json.dumps(out))
    if not res.ok:
        # loud-fail so the skill's coverage gate can detect it by exit code
        reasons = []
        if res.missing_groups:
            reasons.append(f"diagnostic groups not referenced: {res.missing_groups}")
        if not res.engine_cited:
            reasons.append(
                "no engine marker cited (report appears hand-extracted, not grounded "
                f"in the engine output {res.markers_declared})")
        raise SystemExit("report coverage FAILED — " + "; ".join(reasons))
    return 0


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
    try:
        res = _wiki_ingest.ingest_knowledge(
            paths, now=_now_iso(), title=args.title, content=content,
            tags=tags, category=args.category, confidence=args.confidence,
            sources=[s.strip() for s in (args.sources or "").split(",") if s.strip()])
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(res))
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="omx", description="OMX experiment-analysis core")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="normalize a source to IngestResult (prints counts)")
    pi.add_argument("--path", required=True)
    pi.add_argument("--format", required=True)
    pi.set_defaults(func=_cmd_ingest)

    pr = sub.add_parser("reduce", help="reduction verbs")
    rsub = pr.add_subparsers(dest="reduce_cmd", required=True)
    prs = rsub.add_parser("summarize", help="long-form -> CV table")
    prs.add_argument("--path", required=True)
    prs.add_argument("--format", required=True)
    prs.add_argument("--cv-field", default="ss_error", dest="cv_field")
    prs.set_defaults(func=_cmd_reduce_summarize)

    prt = rsub.add_parser(
        "tb-final", help="named final-window means for a tag list (TB/series source)")
    prt.add_argument("--path", required=True, help="series source (TB event file / npz / wandb)")
    prt.add_argument("--format", required=True, help="ingest format (e.g. tensorboard)")
    prt.add_argument("--tag", action="append", default=[], dest="tag",
                     help="scalar tag to reduce (repeatable)")
    prt.add_argument("--window", type=int, default=200,
                     help="trailing samples to average (default 200)")
    prt.set_defaults(func=_cmd_reduce_tb_final)

    ps = sub.add_parser("session-id", help="resolve session id (flag>env>autogen)")
    ps.add_argument("--session-id", default=None, dest="session_id")
    ps.set_defaults(func=_cmd_session_id)

    pe = sub.add_parser("eval", help="run an evaluator command, parse {pass,score?} (Claude-free)")
    pe.add_argument("--command", required=True, help="shell command; LAST stdout line must be the JSON verdict")
    pe.add_argument("--cwd", default=None, help="working dir for the command (default: cwd)")
    pe.add_argument("--timeout", type=int, default=600, help="seconds before the evaluator is killed (status=error)")
    pe.add_argument("--keep-policy", default=None, dest="keep_policy",
                    help="pass_only | score_improvement; when set, embeds a decide_outcome block")
    pe.add_argument("--last-kept-score", type=float, default=None, dest="last_kept_score",
                    help="prior baseline score for score_improvement comparison")
    pe.set_defaults(func=_cmd_eval)

    pp = sub.add_parser("plot", help="render a candidate curve PNG into scratch (Claude-free IO)")
    pp.add_argument("--root", required=True, help="anchor dir under which .omx/ lives")
    pp.add_argument("--session-id", required=True, dest="session_id")
    pp.add_argument("--path", required=True, help="series source (npz/TB/wandb)")
    pp.add_argument("--format", required=True)
    pp.add_argument("--series", required=True, help="series key within the source")
    pp.add_argument("--metric", required=True, help="metric token (output filename field)")
    pp.add_argument("--view", required=True, help="view token (output filename field)")
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

    prc = sub.add_parser(
        "report-coverage",
        help="lint report.md for diagnostic-group + engine-marker completeness (GAP 4; loud-fail)")
    prc.add_argument("--path", required=True, help="path to an exp-analyze report.md")
    prc.add_argument("--root", required=True, help="workspace root holding .omx/profile/metrics.yaml")
    prc.set_defaults(func=_cmd_report_coverage)

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
