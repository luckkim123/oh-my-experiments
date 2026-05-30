"""omx_paths — the single source of truth for every OMX path.

No other module may construct an OMX path by string concatenation; all paths
come from OmxPaths getters (added in later tasks), which validate ids
(loud-fail) before returning.

Two-tier validation (design doc B1):
  - structural tier: fixed regexes, profile-free, always on.
  - vocabulary tier: optional Profile injected per-getter (Task 3+); when
    present, metric/view/agg/source must be in the profile vocab and run_id
    must match the profile regex (if set).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


class OmxPathError(ValueError):
    """Raised on any invalid id or path-construction request (never silent)."""


# --- Structural regexes (B1 tier a): fixed, profile-free ----------------------
# Anchored with \A...\Z (not ^...$): \A/\Z bind strictly to string start/end,
# while $ also matches just before a trailing newline. .fullmatch already guards
# against that, but \A...\Z makes the no-newline intent explicit and robust even
# if a future getter switches to .match/.search.
_TS = r"\d{8}-\d{6}"  # YYYYMMDD-HHMMSS — numeric sort == chrono sort
_ANALYSIS_ID = re.compile(rf"\A{_TS}-[a-z][a-z0-9]*\Z")
_SESSION_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_RUN_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_TOKEN = re.compile(r"\A[a-z0-9][a-z0-9_]*\Z")  # single semantic token; no '__'
_EXT = re.compile(r"\A[a-z0-9]+\Z")


def _require_str(value, label: str) -> str:
    if not isinstance(value, str) or value == "":
        raise OmxPathError(f"{label} must be a non-empty string, got {value!r}")
    return value


def validate_analysis_id(value) -> str:
    v = _require_str(value, "analysis_id")
    if not _ANALYSIS_ID.fullmatch(v):
        raise OmxPathError(
            f"analysis_id {v!r} must match YYYYMMDD-HHMMSS-<verb> (lowercase verb)")
    return v


# proposal_id shares the analysis_id shape (timestamp + lowercase keyword)
validate_proposal_id = validate_analysis_id


def validate_session_id(value) -> str:
    v = _require_str(value, "session_id")
    if not _SESSION_ID.fullmatch(v) or ".." in v:
        raise OmxPathError(f"session_id {v!r} invalid (no separators / '..')")
    return v


def validate_run_id(value) -> str:
    v = _require_str(value, "run_id")
    # _RUN_ID forbids '.', so '..' cannot occur — no extra traversal guard needed
    # (unlike session_id, whose char class allows '.').
    if not _RUN_ID.fullmatch(v):
        raise OmxPathError(f"run_id {v!r} invalid (alnum/_/-, no separators)")
    return v


def validate_token(value, label: str) -> str:
    v = _require_str(value, label)
    if not _TOKEN.fullmatch(v) or "__" in v:
        raise OmxPathError(
            f"{label} {v!r} must be lowercase [a-z0-9_], single token (no '__')")
    return v


def validate_ext(value) -> str:
    v = _require_str(value, "ext")
    if not _EXT.fullmatch(v):
        raise OmxPathError(f"ext {v!r} must be lowercase alphanumeric")
    return v


# --- Profile (B1 tier b): optional vocabulary, populated later by exp-init -----
@dataclass(frozen=True)
class Profile:
    """Vocabulary tier for path validation. exp-init builds this from metrics.yaml.

    All sets default empty (= 'no vocab restriction for that field'); run_id_regex
    None = no profile-specific run_id restriction (structural tier still applies).
    """
    metrics: frozenset = field(default_factory=frozenset)
    views: frozenset = field(default_factory=frozenset)
    aggs: frozenset = field(default_factory=frozenset)
    sources: frozenset = field(default_factory=frozenset)
    run_id_regex: Optional[str] = None

    def __post_init__(self):
        # normalize any iterable (set/list) to frozenset without breaking frozen
        object.__setattr__(self, "metrics", frozenset(self.metrics))
        object.__setattr__(self, "views", frozenset(self.views))
        object.__setattr__(self, "aggs", frozenset(self.aggs))
        object.__setattr__(self, "sources", frozenset(self.sources))
        # Compile run_id_regex now so a malformed pattern fails loud at Profile
        # construction, not silently at first getter call in Task 3+.
        if self.run_id_regex is not None:
            try:
                re.compile(self.run_id_regex)
            except re.error as e:
                raise OmxPathError(f"Profile.run_id_regex invalid: {e}")
