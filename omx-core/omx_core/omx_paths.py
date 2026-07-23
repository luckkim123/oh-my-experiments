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
from pathlib import Path
from typing import Optional

from omx_core.atomic import atomic_dir, atomic_path  # noqa: F401 — re-export, back-compat


class OmxError(Exception):
    """Root of every OMX loud-fail (path, evaluator, decision). Siblings live in
    other modules (e.g. evaluator.EvaluatorError) so callers can catch one base."""


class OmxPathError(OmxError, ValueError):
    """Raised on any invalid id or path-construction request (never silent).

    Multiple-inherits ValueError so pre-#2 `except ValueError` sites still catch it."""


# --- Structural regexes (B1 tier a): fixed, profile-free ----------------------
# Anchored with \A...\Z (not ^...$): \A/\Z bind strictly to string start/end,
# while $ also matches just before a trailing newline. .fullmatch already guards
# against that, but \A...\Z makes the no-newline intent explicit and robust even
# if a future getter switches to .match/.search.
_TS = r"\d{8}-\d{6}"  # YYYYMMDD-HHMMSS — the timestamp component
# Accept BOTH label-before-date (new default: diagnose-20260605-190606) and the
# legacy date-before-verb shape (existing on-disk dirs: 20260605-190606-diagnose).
# Dual-accept so analysis/proposal dirs written before the 2026-06-05 format flip
# keep validating. No omx code sorts analysis_id chronologically (verified grep), so
# verb-first leading does not break any ordering.
_ANALYSIS_ID = re.compile(rf"\A(?:[a-z][a-z0-9]*-{_TS}|{_TS}-[a-z][a-z0-9]*)\Z")
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
            f"analysis_id {v!r} must match <verb>-YYYYMMDD-HHMMSS (lowercase verb)")
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


def validate_group(value) -> str:
    """Validate an optional run-grouping prefix (e.g. ``rsl_rl/exp_a_teacher/dr_sweep``).

    A *group* lets runs cluster under the output_root by experiment_name / purpose
    (``output_root/<group>/<run_id>/...``) instead of flat ``output_root/<run_id>/...``.
    ``None``/``""`` means "no group" (the flat layout) and returns ``""``.

    Each ``/``-separated segment must satisfy the same charset as a run_id
    (``alnum/_/-``); '.' is forbidden, so ``..`` traversal, absolute paths, and empty
    segments (``a//b``, leading/trailing ``/``) are all rejected. Returns the cleaned
    group string (forward-slash joined) for use in path construction.
    """
    if value is None or value == "":
        return ""
    v = _require_str(value, "group")
    segs = v.split("/")
    for seg in segs:
        if not _RUN_ID.fullmatch(seg):  # forbids '', '..', and any bad char
            raise OmxPathError(
                f"group {v!r} invalid: segment {seg!r} must be alnum/_/- (no '', '..', '/')")
    return "/".join(segs)


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

    def seal_json(self) -> Path:
        """profile/seal.json — sha256 seal over the executable profile files (#0).
        Not in _PROFILE_FILES: bootstrap never writes it; profile-seal owns it."""
        return self.profile_dir / "seal.json"

    def tree_yaml(self) -> Path:
        """profile/tree.yaml — the declarative tree schema (R2, D10).
        Not in _PROFILE_FILES: `omx init` writes the generic default only when
        absent; `omx tree-codify` owns replacement."""
        return self.profile_dir / "tree.yaml"

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

    # --- registry/ wiki (permanent, keyword-indexed knowledge layer; build #8) ---
    def wiki_dir(self) -> Path:
        """registry/findings/ — the dir holding all wiki page .md files."""
        return self.omx_dir / "registry" / "findings"

    def wiki_page(self, slug) -> Path:
        """registry/findings/<slug>.md — one wiki page. slug is a single token
        (validate_token blocks '..'/separators), so traversal is impossible."""
        return self.wiki_dir() / f"{self._check_token(slug, 'slug')}.md"

    def wiki_index(self) -> Path:
        """registry/index.md — auto-regenerated catalog (one line per page)."""
        return self.omx_dir / "registry" / "index.md"

    def wiki_log(self) -> Path:
        """registry/log.md — append-only chronicle of wiki operations."""
        return self.omx_dir / "registry" / "log.md"

    def wiki_lock(self) -> Path:
        """registry/.wiki-lock — file mutex for all wiki writes (fcntl)."""
        return self.omx_dir / "registry" / ".wiki-lock"

    def recipes_dir(self) -> Path:
        """Promoted diagnostic recipes (#15) — structured symptom->checks
        checklists exp-analyze/exp-design read before diagnosis. NOT a gated
        deliverable (report_guard does not cover it); the promoting session may
        restructure a recipe after the verb creates it."""
        return self.omx_dir / "recipes"

    # --- state.json (single global file) ---
    def state_json(self) -> Path:
        return self.omx_dir / "state.json"

    def produced_reports_ledger(self) -> Path:
        """Root-level append-only ledger of gate-stamped reports awaiting
        session-end wiki capture (spec 2.2). NOT under scratch/ — the stamp
        write-site (report-coverage) has no session id (D-R3-5)."""
        return self.omx_dir / "state" / "produced-reports.jsonl"

    # --- packaged reference profiles (committed; outside .omx, ships with pkg) ---
    @property
    def reference_dir(self) -> Path:
        """The package's committed reference/ dir (anchored to the install, not
        self.root). Holds shipped reference evaluators (e.g. isaaclab/evaluator.sh)."""
        return Path(__file__).resolve().parent / "reference"

    def reference_evaluator(self, profile_name) -> Path:
        """Path to the COMMITTED reference evaluator.sh for `profile_name` (B4).

        NOT user-elicited; this is the shipped reference exp-init later copies into
        .omx/profile/. Loud-fail if profile_name is not a token or the file is absent.
        """
        name = validate_token(profile_name, "profile_name")
        path = self.reference_dir / name / "evaluator.sh"
        if not path.exists():
            raise OmxPathError(f"reference evaluator not shipped for {name!r}: {path}")
        return path

    # --- B6 checkpoint pointer (run-bound; weights revert target) ---
    def checkpoint_pointer_json(self, run_id) -> Path:
        """runs/<run_id>/checkpoint-pointer.json — the last_kept_checkpoint pointer
        (B6). Standalone 1-key mirror of ledger.last_kept_checkpoint so exp-loop
        reads the weights pointer without parsing the full ledger."""
        return self.run_dir(run_id) / "checkpoint-pointer.json"

    def pending_launch_json(self, run_id) -> Path:
        """runs/<run_id>/pending-launch.json — the next training launch QUEUED by
        exp-loop for human approval (B8). exp-loop NEVER fires a launch; it writes
        this artifact and stops. The human reads it, approves, and launches by
        hand. Run-bound, sits beside the ledger trio."""
        return self.run_dir(run_id) / "pending-launch.json"

    def loop_lock(self, run_id) -> Path:
        """runs/<run_id>/.loop-lock — the per-run O_EXCL lease file (R4 #1,
        D-R4-3). Keyed by the omx session id; creation is the atomic claim, so
        NO atomic_path .tmp dance (a lease must not be rename-replaceable)."""
        return self.run_dir(run_id) / ".loop-lock"

    def state_lock(self) -> Path:
        """.omx/state/.state-lock — the fcntl mutex file guarding every
        state.json load-mutate-save critical section (R4 #1). Under state/ (not
        beside state.json) so the lock file is never mistaken for state."""
        return self.omx_dir / "state" / ".state-lock"

    def loop_marker_json(self, run_id) -> Path:
        """runs/<run_id>/loop-status.json — the loop-completion marker (R4 #7,
        D-R4-8). Written atomically by mark_loop_done; folded into loop-status'
        phase field."""
        return self.run_dir(run_id) / "loop-status.json"

    # --- campaigns/<campaign_id>/ (cross-run ledger, R2 #28) ---
    def campaign_dir(self, campaign_id) -> Path:
        """campaigns/<campaign_id>/ — campaign_id shares the run_id CHARSET
        (single segment; it IS the tree's group segment, D-R2-5) but not the
        profile run_id regex (a campaign is a group name, not a run)."""
        return self.omx_dir / "campaigns" / validate_run_id(campaign_id)

    def campaign_plan(self, campaign_id) -> Path:
        return self.campaign_dir(campaign_id) / "plan.json"

    def campaign_ledger(self, campaign_id) -> Path:
        return self.campaign_dir(campaign_id) / "ledger.jsonl"

    # --- programs/<program-id>/ (cross-campaign program layer, v0.9.0) ---
    def program_dir(self, program_id) -> Path:
        """programs/<program-id>/ — cross-campaign program artifact
        (PLAN.md narrative + program.json header). program_id shares the
        campaign/run_id charset."""
        return self.omx_dir / "programs" / validate_run_id(program_id)

    def program_json(self, program_id) -> Path:
        return self.program_dir(program_id) / "program.json"

    def program_plan_md(self, program_id) -> Path:
        return self.program_dir(program_id) / "PLAN.md"

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

    def _run_base(self, output_root, run_id, group) -> Path:
        """``output_root[/<group>]/<run_id>`` — the run's permanent-tree root.

        *group* (optional) clusters runs by experiment_name / purpose; when falsy the
        layout is the flat ``output_root/<run_id>`` (back-compat). Both group and run_id
        are validated (charset / no traversal) before they touch the path.
        """
        base = self._out_root(output_root)
        grp = validate_group(group)
        rid = self._check_run_id(run_id)
        return (base / grp / rid) if grp else (base / rid)

    def analysis_dir(self, output_root, run_id, analysis_id, *, group=None) -> Path:
        aid = validate_analysis_id(analysis_id)
        return self._run_base(output_root, run_id, group) / "analysis" / aid

    def report_md(self, output_root, run_id, analysis_id, *, group=None) -> Path:
        return self.analysis_dir(output_root, run_id, analysis_id, group=group) / "report.md"

    def report_ko_md(self, output_root, run_id, analysis_id, *, group=None) -> Path:
        """Korean mirror of report.md. report.md stays canonical (wiki / report-parse
        read it); report.ko.md is the human-facing Korean translation alongside it."""
        return self.analysis_dir(output_root, run_id, analysis_id, group=group) / "report.ko.md"

    def manifest_json(self, output_root, run_id, analysis_id, *, group=None) -> Path:
        return self.analysis_dir(output_root, run_id, analysis_id, group=group) / "manifest.json"

    def analysis_plot(self, output_root, run_id, analysis_id, *, metric, view, group=None) -> Path:
        met = self._check_token(metric, "metric", vocab_attr="metrics")
        vw = self._check_token(view, "view", vocab_attr="views")
        return self.analysis_dir(output_root, run_id, analysis_id, group=group) / "plots" / f"{met}__{vw}.png"

    def analysis_table(self, output_root, run_id, analysis_id, *, metric, agg, group=None) -> Path:
        met = self._check_token(metric, "metric", vocab_attr="metrics")
        ag = self._check_token(agg, "agg", vocab_attr="aggs")
        return self.analysis_dir(output_root, run_id, analysis_id, group=group) / "tables" / f"{met}__{ag}.csv"

    def proposal_md(self, output_root, run_id, proposal_id, *, group=None) -> Path:
        pid = validate_proposal_id(proposal_id)
        return self._run_base(output_root, run_id, group) / "proposals" / f"{pid}.md"

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


# atomic_path/atomic_dir moved to omx_core.atomic (om-core vendored file);
# re-exported at the top of this file for back-compat — the ~25 call sites
# across the codebase import from omx_core.omx_paths (or the omx_core
# package root), unaffected.
