"""D-R5-5 grep-guard: after unification, NO omx_core module (nor hooks/handlers.py)
may mint a timestamp with an inline `datetime.now(timezone.utc)...isoformat()` or a
bare `fromisoformat` on a stored instant. Everything goes through omx_core.clock.

Allowlist (the correct implementation must NOT be flagged):
  - clock.py itself (it IS the helper)
  - the two strftime NAMING sites in cli.py (_now_stamp; also datetime.now().strftime
    for tree ts and .trash ts) — human-facing names, never compared (BY DESIGN)
  - the wiki naive-contract sites: wiki/ingest.py, wiki/lint.py (untouched)
  - the delegated-parse sites: lock.py, loop.py (they call clock.parse_iso_utc)
  - the loop-arm --now ENTRY GUARD in cli.py (rejects a naive injection; aware-only)
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "omx-core" / "omx_core"
HANDLERS = REPO / "hooks" / "handlers.py"

# files exempt from the "no inline datetime.now(...).isoformat()" rule
_ISOFORMAT_ALLOW = {
    CORE / "clock.py",
}
# files exempt from the "no bare fromisoformat" rule (delegated-parse or contract)
_FROMISO_ALLOW = {
    CORE / "clock.py",          # the normalizing parse lives here
    CORE / "lock.py",           # delegates to clock.parse_iso_utc (import present, no bare call)
    CORE / "loop.py",           # _parse_iso delegates
    CORE / "wiki" / "lint.py",  # wiki naive contract (tzinfo-strip) — untouched
    CORE / "cli.py",            # the loop-arm --now aware-only entry guard (line ~1002)
}

_INLINE_NOW = re.compile(r"datetime\.now\(\s*timezone\.utc\s*\)\s*\.\s*(?:replace\([^)]*\)\s*\.\s*)?isoformat\(\)")
_FROMISO = re.compile(r"\.fromisoformat\(")


def _py_files():
    return list(CORE.rglob("*.py")) + [HANDLERS]


def test_no_stray_inline_now_isoformat():
    offenders = []
    for f in _py_files():
        if f in _ISOFORMAT_ALLOW:
            continue
        if _INLINE_NOW.search(f.read_text(encoding="utf-8")):
            offenders.append(str(f.relative_to(REPO)))
    assert not offenders, (
        "inline datetime.now(timezone.utc).isoformat() outside clock.py — use "
        "clock.now_iso()/now_iso_naive():\n" + "\n".join(offenders))


def test_no_stray_fromisoformat():
    offenders = []
    for f in _py_files():
        if f in _FROMISO_ALLOW:
            continue
        if _FROMISO.search(f.read_text(encoding="utf-8")):
            offenders.append(str(f.relative_to(REPO)))
    assert not offenders, (
        "bare .fromisoformat( outside the allowlist — use clock.parse_iso_utc():\n"
        + "\n".join(offenders))


def test_clock_module_exports_the_three_helpers():
    from omx_core import clock
    assert callable(clock.now_iso)
    assert callable(clock.now_iso_naive)
    assert callable(clock.parse_iso_utc)
