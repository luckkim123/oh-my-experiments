"""omx_core.clock — the single timestamp helper (D-R5-5).

Ends the naive-cli / aware-evaluator `_now_iso` split and the "AWARE UTC — never
_now_iso()" comments scattered at every gate call site. One helper, one parse,
zero per-site vigilance.

Three functions, three jobs (critic C1 — instants unify, naming stays local,
THE WIKI STAYS NAIVE):
  - now_iso()       aware UTC — every stored/compared NON-wiki instant.
  - now_iso_naive() the same instant, tzinfo stripped — the wiki's on-disk format
                    (wiki/ingest.py REJECTS an aware `now`; wiki/lint subtracts
                    naive-vs-naive). Wiki-feeding call sites use THIS, never now_iso.
  - parse_iso_utc(value, label) loud-fail parse that NORMALIZES: a naive value
                    gets UTC attached. Exact, not a guess — every legacy writer was
                    a UTC instant (cli _now_iso was aware-UTC with tzinfo stripped;
                    evaluator was aware-UTC). Used by every parse-and-compare site.
"""
from __future__ import annotations

from datetime import datetime, timezone

from omx_core.omx_paths import OmxError


def now_iso() -> str:
    """Aware-UTC ISO string (with +00:00 offset). Every non-wiki stored/compared
    instant (loop lease armed_at, marker ended_at, gate now, seal/stamp/campaign
    timestamps)."""
    return datetime.now(timezone.utc).isoformat()


def now_iso_naive() -> str:
    """The same instant as now_iso() with tzinfo stripped — the wiki's naive-UTC
    on-disk format. Wiki writers use THIS: wiki/ingest.py raises on an aware `now`
    and wiki/lint subtracts naively, so an aware value would break the wiki."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def parse_iso_utc(value, label: str) -> datetime:
    """Parse an ISO-8601 instant to an AWARE-UTC datetime, normalizing a naive
    value (attach UTC). Loud-fail (OmxError, naming `label`) on a non-string or an
    unparseable value. Safe to normalize: the legacy writers this parses were all
    UTC instants, so attaching UTC to a naive value is exact."""
    if not isinstance(value, str) or not value.strip():
        raise OmxError(f"{label} must be a non-empty ISO-8601 string, got {value!r}.")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as e:
        raise OmxError(f"{label} is not a valid ISO-8601 timestamp: {value!r}.") from e
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
