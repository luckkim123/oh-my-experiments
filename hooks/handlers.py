"""omx hook handlers — pure functions (stdin dict -> decision dict | None).

report_guard (spec 3.2): deny Edit/Write on gated exp-analyze deliverables
(analysis/<analysis_id>/{report.md, report.ko.md, manifest.json}). The
legitimate write path is Bash -> omx_core atomic_path (exp-analyze's writer),
which a PreToolUse Edit|Write matcher never sees — so the guard cannot fire on
a gate-passing write. Closes the 0.1.14 hand-Edit incident at edit time; the
intentional friction on one-character fixes is accepted (that WAS the incident).
Fail-open: unparseable input or an unavailable omx_core -> allow (None).
"""
import re
from pathlib import PurePosixPath

_GATED_NAMES = frozenset({"report.md", "report.ko.md", "manifest.json"})

# Local mirror of omx_paths._ANALYSIS_ID; refreshed from omx_core when importable.
_TS = r"\d{8}-\d{6}"
_ANALYSIS_ID = re.compile(rf"\A(?:[a-z][a-z0-9]*-{_TS}|{_TS}-[a-z][a-z0-9]*)\Z")
try:  # prefer the core's regex so the two can never drift silently
    from omx_core.omx_paths import _ANALYSIS_ID as _CORE_ANALYSIS_ID
    _ANALYSIS_ID = _CORE_ANALYSIS_ID
except Exception:
    pass  # stdlib fallback keeps the guard alive without an installed core

_DENY_REASON = (
    "omx report-guard: gated deliverables (analysis/<id>/report.md, report.ko.md, "
    "manifest.json) are written only by the exp-analyze atomic_path writer — "
    "re-enter the exp-analyze skill (RE-analysis) with the old report as BASE "
    "instead of hand-editing; report-coverage will re-stamp it. "
    "Escape hatch (explicit, logged intent): OMX_SKIP_HOOKS=report_guard."
)


def report_guard(payload):
    if payload.get("tool_name") not in ("Edit", "Write"):
        return None
    file_path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not file_path:
        return None
    p = PurePosixPath(file_path.replace("\\", "/"))
    if p.name not in _GATED_NAMES:
        return None
    parts = p.parts
    if len(parts) < 3:
        return None
    if not _ANALYSIS_ID.fullmatch(parts[-2]) or parts[-3] != "analysis":
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": _DENY_REASON,
    }}


HANDLERS = {"report_guard": report_guard}
