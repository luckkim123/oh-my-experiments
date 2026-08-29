"""omx_core.wiki.capture — session-end breadcrumb writer (#11, spec 3.7).

The write half of the read-only `wiki add --from-report` extractor: every parsed
[FINDING] becomes a LOW-confidence stub page (category session-log). A session
that skips manual curation still leaves breadcrumbs; lint's low-confidence /
low-quality checks queue them for promotion. Duplicate-vs-manual-curation is
absorbed by slug append-merge (INV-2).
"""
from __future__ import annotations

from omx_core.omx_paths import OmxPaths
from omx_core.report import parse_findings
from omx_core.wiki.hq_backend import write_knowledge
from omx_core.wiki.quality import score_page

_TITLE_MAX = 80


def capture_session(paths: OmxPaths, *, now: str, report_text: str,
                    report_ref: str, run_id: str | None = None) -> dict:
    findings = parse_findings(report_text)  # loud-fail: broken report is a signal
    tags = ["auto-captured"] + ([run_id] if run_id else [])
    slugs = []
    for f in findings:
        title = f.claim[:_TITLE_MAX]
        content = (f"{f.claim}\n\n[EVIDENCE: {f.evidence}]\n"
                   f"[CONFIDENCE: {f.confidence}]\n\nsource report: {report_ref}")
        score, reasons = score_page(content, tags, title=title)
        res = write_knowledge(
            paths.root, now=now, title=title, content=content, tags=tags,
            category="session-log", confidence="low",
            # No `sources=`: hq has no provenance list, and the report ref is
            # already inside the body above ("source report: ..."), so nothing
            # is lost by dropping the argument the old wiki schema carried.
            quality_score=score, quality_reasons=reasons)
        slugs.append(res["slug"])
    return {"captured": len(slugs), "slugs": slugs}


def flush_produced_reports(paths: OmxPaths, *, now: str) -> dict:
    """Report pending ledger size while SessionEnd capture is deliberately off.

    There has never been a produced-reports ledger or auto-captured page in
    this harness. Keeping the ledger intact makes the disabled path reversible
    without discarding evidence.
    """
    ledger = paths.produced_reports_ledger()
    if not ledger.exists():
        return {"captured": 0, "skipped": 0, "disabled": True}
    try:
        skipped = sum(1 for line in ledger.read_text(encoding="utf-8").splitlines()
                      if line.strip())
    except OSError:
        skipped = 0
    return {"captured": 0, "skipped": skipped, "disabled": True}
