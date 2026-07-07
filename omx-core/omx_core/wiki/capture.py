"""omx_core.wiki.capture — session-end breadcrumb writer (#11, spec 3.7).

The write half of the read-only `wiki add --from-report` extractor: every parsed
[FINDING] becomes a LOW-confidence stub page (category session-log). A session
that skips manual curation still leaves breadcrumbs; lint's low-confidence /
low-quality checks queue them for promotion. Duplicate-vs-manual-curation is
absorbed by slug append-merge (INV-2).
"""
from __future__ import annotations

from pathlib import Path

from omx_core.omx_paths import OmxPaths
from omx_core.report import parse_findings
from omx_core.wiki.ingest import ingest_knowledge
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
        res = ingest_knowledge(
            paths, now=now, title=title, content=content, tags=tags,
            category="session-log", confidence="low",
            sources=[report_ref], quality_score=score, quality_reasons=reasons)
        slugs.append(res["slug"])
    return {"captured": len(slugs), "slugs": slugs}


def flush_produced_reports(paths: OmxPaths, *, now: str) -> dict:
    """Capture every ledger-recorded stamped report into session-log stubs,
    then truncate the ledger (spec 2.2). RESCUE PATH SEMANTICS: never loud-fail
    — a broken line/report is warned to stderr and skipped; capture_session is
    append-merge so re-flushing is a no-op merge (truncation is an optimization,
    not a correctness requirement). The truncate-vs-concurrent-append race is
    accepted for a workstation harness."""
    import json as _json
    import sys as _sys

    from omx_core.integrity import verify_report
    from omx_core.omx_paths import atomic_path

    ledger = paths.produced_reports_ledger()
    if not ledger.exists():
        return {"captured": 0, "skipped": 0}
    try:
        text = ledger.read_text(encoding="utf-8")
    except OSError as e:
        print(f"WARNING: produced-reports ledger unreadable: {e}", file=_sys.stderr)
        return {"captured": 0, "skipped": 0}

    seen, captured, skipped = set(), 0, 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            entry = _json.loads(line)
            report_path = Path(entry["report"])
        except (ValueError, KeyError, TypeError):
            print(f"WARNING: skipping unparseable ledger line: {line[:80]!r}",
                  file=_sys.stderr)
            continue
        key = str(report_path)
        if key in seen:
            continue
        seen.add(key)
        if not report_path.exists():
            skipped += 1
            continue
        v = verify_report(str(report_path))
        if v["status"] in ("mismatch", "no-gates"):
            print(f"WARNING: report integrity {v['status']} — not capturing "
                  f"{report_path}", file=_sys.stderr)
            skipped += 1
            continue
        try:
            capture_session(paths, now=now,
                            report_text=report_path.read_text(encoding="utf-8"),
                            report_ref=str(report_path), run_id=None)
            captured += 1
        except Exception as e:  # rescue path: one bad report never kills the flush
            print(f"WARNING: capture failed for {report_path}: {e}", file=_sys.stderr)
            skipped += 1
    with atomic_path(ledger) as tmp:
        Path(tmp).write_text("")
    return {"captured": captured, "skipped": skipped}
