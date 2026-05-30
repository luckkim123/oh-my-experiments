"""omx_core.cli — the `omx` command (Claude-free verbs: ingest, reduce, session-id).

These verbs are pure Python so they are unit-testable from Bash with no Claude
or Isaac dependency. Skills (builds #3-#6) shell out to these.
"""
import argparse
import json
import math
import os
import sys

from omx_core.ingest.eval_summary import EvalSummaryAdapter
from omx_core.ingest.csv_longform import LongFormCsvAdapter
from omx_core.omx_paths import resolve_session_id
from omx_core.reduce.summarize import to_dataframe, add_cv
from omx_core.evaluator import run_evaluator
from omx_core.decision import decide_outcome, parse_keep_policy
from omx_core.omx_paths import OmxError

def _finite_or_none(x):
    """Map non-finite floats (nan/inf) to None so json.dumps emits valid JSON null."""
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


_ADAPTERS = {
    "eval_summary": EvalSummaryAdapter,
    "csv_longform": LongFormCsvAdapter,
}


def _ingest(path, fmt):
    if fmt not in _ADAPTERS:
        raise SystemExit(f"unknown --format {fmt!r}; choose from {sorted(_ADAPTERS)}")
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


def _cmd_session_id(args) -> int:
    sid = resolve_session_id(
        explicit=args.session_id,
        env=os.environ.get("OMX_SESSION_ID"),
        autogen=f"{_now_stamp()}-{os.getpid()}",
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
    print(json.dumps(out))
    return 0 if rec["status"] in ("pass", "fail") else 1


def _now_stamp() -> str:
    # local wall-clock; deterministic format YYYYMMDD-HHMMSS
    import time
    return time.strftime("%Y%m%d-%H%M%S", time.localtime())


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

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2


if __name__ == "__main__":
    sys.exit(main())
