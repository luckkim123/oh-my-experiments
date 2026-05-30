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

import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
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


# --- OmxPaths: single source of truth for every .omx/ path -------------------
_PROFILE_FILES = frozenset({"evaluator.sh", "metrics.yaml", "rules.md", "launch.sh"})


class OmxPaths:
    """Single source of truth for every OMX path.

    `root` is the fixed anchor under which `.omx/` lives (design H4). It is
    REQUIRED and resolved before any output_root value. The permanent output
    tree (output_root) is passed per-getter (Task 4), never derived here.

    Two-tier validation (B1): structural id checks always run; vocabulary checks
    (metric/view/agg/source in profile vocab, run_id matches profile regex) run
    only when a Profile is attached.
    """

    def __init__(self, root, profile: Optional[Profile] = None):
        if root is None or str(root) == "":
            raise OmxPathError("OmxPaths root is required (the .omx anchor)")
        self.root = Path(root)
        self.omx_dir = self.root / ".omx"
        self.profile = profile

    # --- profile/ (permanent user tuning) ---
    @property
    def profile_dir(self) -> Path:
        return self.omx_dir / "profile"

    def profile_file(self, name: str) -> Path:
        if name not in _PROFILE_FILES:
            raise OmxPathError(
                f"profile file {name!r} not in {sorted(_PROFILE_FILES)}")
        return self.profile_dir / name

    # --- runs/<run_id>/ (run-bound) ---
    def run_dir(self, run_id) -> Path:
        return self.omx_dir / "runs" / self._check_run_id(run_id)

    def results_tsv(self, run_id) -> Path:
        return self.run_dir(run_id) / "results.tsv"

    def ledger_json(self, run_id) -> Path:
        return self.run_dir(run_id) / "ledger.json"

    def decision_log(self, run_id) -> Path:
        return self.run_dir(run_id) / "decision-log.md"

    def cache_path(self, run_id, *, source, metric) -> Path:
        src = self._check_token(source, "source", vocab_attr="sources")
        met = self._check_token(metric, "metric", vocab_attr="metrics")
        return self.run_dir(run_id) / "cache" / f"{src}__{met}.npz"

    # --- scratch/<session_id>/ (session-bound; session_id MANDATORY, B2) ---
    def scratch_dir(self, *, session_id) -> Path:
        return self.omx_dir / "scratch" / validate_session_id(session_id)

    def scratch_plots(self, *, session_id) -> Path:
        return self.scratch_dir(session_id=session_id) / "plots"

    def scratch_py(self, *, session_id) -> Path:
        return self.scratch_dir(session_id=session_id) / "py"

    def scratch_notes(self, *, session_id) -> Path:
        return self.scratch_dir(session_id=session_id) / "notes.md"

    # --- registry/ (permanent discovery index) ---
    def registry_index(self) -> Path:
        return self.omx_dir / "registry" / "INDEX.md"

    def finding(self, slug) -> Path:
        return self.omx_dir / "registry" / "findings" / f"{self._check_token(slug, 'slug')}.md"

    # --- state.json (single global file) ---
    def state_json(self) -> Path:
        return self.omx_dir / "state.json"

    # --- permanent output tree (output_root passed per-getter; design 10.1) ---
    # These live OUTSIDE .omx/. output_root originates from metrics.yaml and is
    # supplied by the caller every call; it is never derived from self.root.
    def _out_root(self, output_root) -> Path:
        """Return output_root as a Path.

        output_root is CALLER-TRUSTED (it is the user's chosen permanent-tree
        root, from metrics.yaml) — only its presence is checked, its content is
        intentionally NOT validated (it may be any absolute/relative path the
        user picked). The untrusted parts are the ids (run_id/analysis_id/
        metric/...), which every getter validates separately.
        """
        if output_root is None or str(output_root) == "":
            raise OmxPathError("output_root is required for permanent-tree paths")
        return Path(output_root)

    def analysis_dir(self, output_root, run_id, analysis_id) -> Path:
        base = self._out_root(output_root)
        rid = self._check_run_id(run_id)
        aid = validate_analysis_id(analysis_id)
        return base / rid / "analysis" / aid

    def report_md(self, output_root, run_id, analysis_id) -> Path:
        return self.analysis_dir(output_root, run_id, analysis_id) / "report.md"

    def manifest_json(self, output_root, run_id, analysis_id) -> Path:
        return self.analysis_dir(output_root, run_id, analysis_id) / "manifest.json"

    def analysis_plot(self, output_root, run_id, analysis_id, *, metric, view) -> Path:
        met = self._check_token(metric, "metric", vocab_attr="metrics")
        vw = self._check_token(view, "view", vocab_attr="views")
        return self.analysis_dir(output_root, run_id, analysis_id) / "plots" / f"{met}__{vw}.png"

    def analysis_table(self, output_root, run_id, analysis_id, *, metric, agg) -> Path:
        met = self._check_token(metric, "metric", vocab_attr="metrics")
        ag = self._check_token(agg, "agg", vocab_attr="aggs")
        return self.analysis_dir(output_root, run_id, analysis_id) / "tables" / f"{met}__{ag}.csv"

    def proposal_md(self, output_root, run_id, proposal_id) -> Path:
        base = self._out_root(output_root)
        rid = self._check_run_id(run_id)
        pid = validate_proposal_id(proposal_id)
        return base / rid / "proposals" / f"{pid}.md"

    # --- internal 2-tier validation helpers ---
    def _check_run_id(self, run_id) -> str:
        rid = validate_run_id(run_id)
        if self.profile is not None and self.profile.run_id_regex is not None:
            if not re.fullmatch(self.profile.run_id_regex, rid):
                raise OmxPathError(
                    f"run_id {rid!r} fails profile regex {self.profile.run_id_regex!r}")
        return rid

    def _check_token(self, value, label, vocab_attr: Optional[str] = None) -> str:
        v = validate_token(value, label)
        if self.profile is not None and vocab_attr is not None:
            vocab = getattr(self.profile, vocab_attr)
            if vocab and v not in vocab:
                raise OmxPathError(
                    f"{label} {v!r} not in profile {vocab_attr} {sorted(vocab)}")
        return v


# =============================================================================
# Module-level helpers (Task 5)
# =============================================================================

def resolve_session_id(explicit=None, env=None, autogen=None) -> str:
    """B2 precedence: explicit flag -> env -> autogen(). Validates the result.

    `autogen` is a zero-arg callable (the CLI supplies one building
    '<YYYYMMDD-HHMMSS>-<pid>'); kept injectable so this module stays pure
    (no datetime/getpid baked in -> deterministic tests). Raises OmxPathError
    if nothing resolves or the resolved id is structurally invalid.
    """
    candidate = explicit or env
    if not candidate:
        if autogen is None:
            raise OmxPathError("session_id unresolved: no explicit/env/autogen")
        candidate = autogen()
    return validate_session_id(candidate)


@contextmanager
def atomic_path(target):
    """Yield a '.tmp' sibling; on clean exit os.replace -> target (atomic).

    On exception the .tmp is removed and target is untouched, so partial
    artifacts never pollute the clean tree (design 10.1). Parent dirs created.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        yield tmp
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise
    else:
        os.replace(tmp, target)


@contextmanager
def atomic_dir(target):
    """Like atomic_path but for a directory: build under '<name>.tmp/', then
    os.replace the whole dir onto target on clean exit; discard on exception.

    Linux note: os.replace onto a directory requires `target` to NOT exist or be
    empty (a non-empty existing dir raises OSError Errno 39). OMX analysis ids
    carry an HHMMSS timestamp so collisions are near-impossible; if a caller
    genuinely needs to overwrite, it must shutil.rmtree(target) first — this
    helper deliberately does NOT auto-delete an existing target (silently
    destroying prior output is a worse failure than a loud Errno 39).
    """
    import shutil
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        yield tmp
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    else:
        # os.replace is OUTSIDE the except above; guard it so a failed promotion
        # (e.g. Errno 39 on a non-empty target) doesn't leak the .tmp dir.
        try:
            os.replace(tmp, target)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
