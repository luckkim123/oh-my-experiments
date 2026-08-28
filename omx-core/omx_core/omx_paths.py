"""omx_paths — the single source of truth for every OMX path.

No other module may construct an OMX path by string concatenation; all paths
come from OmxPaths getters (added in later tasks), which validate ids
(loud-fail) before returning.

Two-tier validation (design doc B1):
  - structural tier: fixed regexes, profile-free, always on.
  - vocabulary tier: optional Profile injected per-getter (Task 3+); when
    present, metric/view/agg/source must be in the profile vocab and run_id
    must match the profile regex (if set).

--- .hq/ cutover (om* store unification P6) --------------------------------
This module also resolves the unified `.hq` store alongside the legacy
`.omx` one, mirroring oh-my-project's hooks/omp_paths.py (reference:
~/oh-my-orchestrator/skills/harness/references/store-spec.md §3 the four
layers, §6 the four-state gate, §7 fallback). Two rules, not interchangeable:

**1. The anchor is the switch, not the release.** A write goes to `.hq/`
when — and only when — the project root carries a parseable `.hq/.anchor`.
Without one it goes to `.omx/`, exactly where it went before.

**2. Every OMX artifact getter here resolves via `_write()`, never `_read()`
alone.** Unlike omp (mostly static per-project config, read far more than
written), almost everything OMX names is a freshly-created entity — a new
run_id, campaign_id, program_id, scratch session_id, wiki slug — and `_write`
degrades to exactly `_read`'s answer whenever the artifact already exists
under either store (its branches 2/3 are pure existence checks, same as
`_read`). The two diverge only when NEITHER path holds the artifact yet —
i.e. the entity is being created for the first time — where `_write`
correctly lands a fresh, anchored write at the new location and `_read`
would incorrectly strand it at legacy forever. `_read` is still implemented
below (the reference structure calls for the pair), but no current OMX
getter calls it.

Two lock files (`.wiki-lock`, `.state-lock`) are recreated on demand, so
there's no migration concern for either — each is still resolved via its own
`_write()` call rather than derived from a sibling getter, because the
legacy/new relationship between a lock and its logical directory is not
consistent: `.wiki-lock` sits BESIDE `registry/findings/` in the legacy
layout but INSIDE `community/wiki/` in the new one, so deriving it from
wiki_dir() would silently change the legacy path too.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from omx_core.atomic import atomic_dir, atomic_path  # noqa: F401 — re-export, back-compat

HQ_ROOT = ".hq"
LEGACY_ROOT = ".omx"

# --- layer roots (store-spec section 3); "experiments" is OMX's harness
# subfolder under config/runtime/work — community/ carries no such subfolder
# per the mapping table (community/wiki, community/recipes, community/programs). ---

ANCHOR_REL = f"{HQ_ROOT}/.anchor"
_CONFIG_REL = f"{HQ_ROOT}/config/experiments"
_COMMUNITY_REL = f"{HQ_ROOT}/community"
_RUNTIME_REL = f"{HQ_ROOT}/runtime/experiments"
_WORK_REL = f"{HQ_ROOT}/work/experiments"

_ANCHOR_ID_RE = re.compile(r"^id:\s*(\S.*)$")


def legacy_root(base) -> Path:
    """The legacy store directory itself, given the project root `base`."""
    return Path(base) / LEGACY_ROOT


def anchor_file(base) -> Path:
    return Path(base) / ANCHOR_REL


def config_dir(base) -> Path:
    return Path(base) / _CONFIG_REL


def community_dir(base) -> Path:
    return Path(base) / _COMMUNITY_REL


def runtime_dir(base) -> Path:
    return Path(base) / _RUNTIME_REL


def work_dir(base) -> Path:
    return Path(base) / _WORK_REL


# --- anchor parse and the four-state gate (store-spec sections 2 and 6) -----

class AnchorError(Exception):
    """The anchor file exists but does not parse — a corrupt store, never an
    absent one."""


def parse_anchor_id(path) -> str:
    """Exactly one non-empty line `id: <value>` after stripping one trailing
    newline. Anything else raises. A 10-line reimplementation of omo's
    `hq.anchor.parse_anchor` rather than a cross-plugin import, mirroring
    omp_paths.py's own choice: omx cannot assume oh-my-orchestrator is
    installed."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise AnchorError(f"{path}: cannot read anchor file: {e}") from e
    text = raw[:-1] if raw.endswith("\n") else raw
    non_empty = [ln for ln in text.split("\n") if ln.strip() != ""]
    if len(non_empty) != 1:
        raise AnchorError(
            f"{path}: expected exactly one non-empty line, found {len(non_empty)}")
    m = _ANCHOR_ID_RE.match(non_empty[0])
    if not m:
        raise AnchorError(
            f"{path}: line does not match 'id: <value>': {non_empty[0]!r}")
    value = m.group(1).strip()
    if not value:
        raise AnchorError(f"{path}: empty id value")
    return value


def has_anchor(base) -> bool:
    """True when `base` carries a *parseable* anchor. An unparseable one is
    False here and `corrupt` in `gate_state` — the write switch must not flip
    on a broken file."""
    f = anchor_file(base)
    if not f.is_file():
        return False
    try:
        parse_anchor_id(f)
        return True
    except AnchorError:
        return False


def has_legacy_store(base) -> bool:
    return legacy_root(base).is_dir()


def has_store(base) -> bool:
    """True when `base` is an omx project under either store."""
    return anchor_file(base).is_file() or has_legacy_store(base)


GATE_OFF = "off"
GATE_LEGACY = "legacy"
GATE_NORMAL = "normal"
GATE_CORRUPT = "corrupt"


def gate_state(base) -> str:
    """store-spec section 6, the pair (legacy store, anchor) — never a single
    marker.

    off      no legacy store, no anchor   — not an omx project; hooks exit 0
    legacy   legacy store, no anchor      — warn, read via fallback
    normal   anchor present and parseable
    corrupt  anchor present, unparseable  — loud, never silent
    """
    f = anchor_file(base)
    if f.is_file():
        try:
            parse_anchor_id(f)
            return GATE_NORMAL
        except AnchorError:
            return GATE_CORRUPT
    return GATE_LEGACY if has_legacy_store(base) else GATE_OFF


# --- resolution: read new-then-legacy, write anchor-gated -------------------

def _read(new: Path, legacy: Path) -> Path:
    """Existence of the specific new path is the whole test."""
    return new if new.exists() else legacy


def _write(base, new: Path, legacy: Path) -> Path:
    """The anchor, not the release, decides — and an anchored root whose
    files have not been copied yet keeps writing where the content still is.

    Only when NEITHER path holds this artifact — an anchored root creating a
    brand new entity — does the new path win by default."""
    if not has_anchor(base):
        return legacy
    if new.exists():
        return new
    return legacy if legacy.exists() else new


def iter_store_entries(new: Path, legacy: Path) -> dict:
    """Enumerate immediate children of BOTH `new` and `legacy`, unioned by
    entry name — store-spec §7 stage 1 ('write new, read both'). Listing is a
    read, and unlike a single-entity getter's `_write()` there is no single
    correct path to test: a project mid-fallback can have some entities
    already migrated (new) and some not yet (legacy), so enumeration must
    look at both roots or it silently omits whichever half it skipped.

    The new entry wins a name collision — same precedence as `_write`'s
    branch 2 (an existing new-store entry is authoritative). Neither root
    need exist; a missing one just contributes nothing (not an error)."""
    out = {}
    if legacy.is_dir():
        for child in legacy.iterdir():
            out[child.name] = child
    if new.is_dir():
        for child in new.iterdir():
            out[child.name] = child  # overwrites legacy on a name collision
    return out


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
        self.omx_dir = self.root / LEGACY_ROOT
        self.profile = profile

    # --- profile/ (permanent user tuning) ---
    @property
    def profile_dir(self) -> Path:
        return _write(self.root, config_dir(self.root) / "profile",
                      self.omx_dir / "profile")

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
        rid = self._check_run_id(run_id)
        return _write(self.root, work_dir(self.root) / "runs" / rid,
                      self.omx_dir / "runs" / rid)

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
        sid = validate_session_id(session_id)
        return _write(self.root, runtime_dir(self.root) / "scratch" / sid,
                      self.omx_dir / "scratch" / sid)

    def scratch_plots(self, *, session_id) -> Path:
        return self.scratch_dir(session_id=session_id) / "plots"

    def scratch_py(self, *, session_id) -> Path:
        return self.scratch_dir(session_id=session_id) / "py"

    def scratch_notes(self, *, session_id) -> Path:
        return self.scratch_dir(session_id=session_id) / "notes.md"

    # --- registry/ wiki (permanent, keyword-indexed knowledge layer; build #8) ---
    def wiki_dir(self) -> Path:
        """registry/findings/ (legacy) -> community/wiki/ (new) — the dir
        holding all wiki page .md files."""
        return _write(self.root, community_dir(self.root) / "wiki",
                      self.omx_dir / "registry" / "findings")

    def wiki_page(self, slug) -> Path:
        """<wiki_dir>/<slug>.md — one wiki page. slug is a single token
        (validate_token blocks '..'/separators), so traversal is impossible."""
        return self.wiki_dir() / f"{self._check_token(slug, 'slug')}.md"

    def wiki_index(self) -> Path:
        """registry/index.md (legacy) -> community/wiki/index.md (new) —
        auto-regenerated catalog (one line per page)."""
        return _write(self.root, community_dir(self.root) / "wiki" / "index.md",
                      self.omx_dir / "registry" / "index.md")

    def wiki_log(self) -> Path:
        """registry/log.md (legacy) -> runtime/experiments/registry/log.md
        (new) — append-only chronicle of wiki operations."""
        return _write(self.root, runtime_dir(self.root) / "registry" / "log.md",
                      self.omx_dir / "registry" / "log.md")

    def wiki_lock(self) -> Path:
        """registry/.wiki-lock (legacy, a SIBLING of registry/findings/, not
        nested inside it) -> community/wiki/.wiki-lock (new, nested inside
        wiki_dir()'s new resolution). The legacy/new relationship to wiki_dir()
        differs, so this is resolved independently rather than derived from
        wiki_dir() — deriving it would nest it under legacy findings/, which
        it never was. File mutex for all wiki writes (fcntl)."""
        return _write(self.root, community_dir(self.root) / "wiki" / ".wiki-lock",
                      self.omx_dir / "registry" / ".wiki-lock")

    def recipes_dir(self) -> Path:
        """recipes/ (legacy) -> community/recipes/ (new). Promoted diagnostic
        recipes (#15) — structured symptom->checks checklists exp-analyze/
        exp-design read before diagnosis. NOT a gated deliverable (report_guard
        does not cover it); the promoting session may restructure a recipe
        after the verb creates it."""
        return _write(self.root, community_dir(self.root) / "recipes",
                      self.omx_dir / "recipes")

    # --- state.json (single global file) ---
    def state_json(self) -> Path:
        """state.json (legacy) -> runtime/experiments/state.json (new)."""
        return _write(self.root, runtime_dir(self.root) / "state.json",
                      self.omx_dir / "state.json")

    def produced_reports_ledger(self) -> Path:
        """state/produced-reports.jsonl (legacy) ->
        config/experiments/produced-reports.jsonl (new, no `state/` subfolder
        — the store-spec layer rules put this in config/, loss is not
        harmless). Root-level append-only ledger of gate-stamped reports
        awaiting session-end wiki capture (spec 2.2). NOT under scratch/ — the
        stamp write-site (report-coverage) has no session id (D-R3-5)."""
        return _write(self.root, config_dir(self.root) / "produced-reports.jsonl",
                      self.omx_dir / "state" / "produced-reports.jsonl")

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

    def trash_root(self) -> Path:
        """.trash/ (legacy) -> runtime/experiments/trash/ (new — no leading
        dot; the whole runtime/ layer is already .gitignore'd, so a child
        does not need its own dot-hiding). clean.py's own cleanup staging
        area (#22); no row in the artifact mapping table since it is not a
        migrated artifact. Resolved via _write() like every other getter, so
        an anchored project's `clean --apply`/`purge-trash` never touches
        .omx/ — critically, that means a purge followed by a clean sweep
        cannot recreate .omx/.trash and silently undo the purge."""
        return _write(self.root, runtime_dir(self.root) / "trash",
                      self.omx_dir / ".trash")

    def state_lock(self) -> Path:
        """state/.state-lock (legacy) -> runtime/experiments/state/.state-lock
        (new, KEEPS the `state/` subfolder unlike state.json itself) — the
        fcntl mutex file guarding every state.json load-mutate-save critical
        section (R4 #1). Under state/ (not beside state.json) so the lock file
        is never mistaken for state. Recreated on demand -> no migration
        concern; resolved directly (not derived from state_json(), whose new
        location diverges — no `state/` subfolder)."""
        return _write(self.root, runtime_dir(self.root) / "state" / ".state-lock",
                      self.omx_dir / "state" / ".state-lock")

    def loop_marker_json(self, run_id) -> Path:
        """runs/<run_id>/loop-status.json — the loop-completion marker (R4 #7,
        D-R4-8). Written atomically by mark_loop_done; folded into loop-status'
        phase field."""
        return self.run_dir(run_id) / "loop-status.json"

    # --- campaigns/<campaign_id>/ (cross-run ledger, R2 #28) ---
    def campaign_dir(self, campaign_id) -> Path:
        """campaigns/<campaign_id>/ (legacy) ->
        work/experiments/campaigns/<campaign_id>/ (new). campaign_id shares
        the run_id CHARSET (single segment; it IS the tree's group segment,
        D-R2-5) but not the profile run_id regex (a campaign is a group name,
        not a run)."""
        cid = validate_run_id(campaign_id)
        return _write(self.root, work_dir(self.root) / "campaigns" / cid,
                      self.omx_dir / "campaigns" / cid)

    def campaign_plan(self, campaign_id) -> Path:
        return self.campaign_dir(campaign_id) / "plan.json"

    def campaign_ledger(self, campaign_id) -> Path:
        return self.campaign_dir(campaign_id) / "ledger.jsonl"

    def campaigns_root(self) -> tuple:
        """(new, legacy) campaigns root DIRECTORIES — for enumeration
        (iter_store_entries), not a single entity. campaign_dir(id) resolves
        ONE campaign via _write(); listing every campaign needs both trees
        (store-spec §7 stage 1: 'write new, read both'), since a project
        mid-fallback can have some campaigns already migrated and some not."""
        return (work_dir(self.root) / "campaigns", self.omx_dir / "campaigns")

    # --- programs/<program-id>/ (cross-campaign program layer, v0.9.0) ---
    def program_dir(self, program_id) -> Path:
        """programs/<program-id>/ (legacy) -> community/programs/<program-id>/
        (new) — cross-campaign program artifact's narrative half (PLAN.md,
        HANDOFF.md, and anything else a caller writes alongside them).
        program_json() below resolves the config-layer program.json header
        SEPARATELY (its new location diverges from this one). program_id
        shares the campaign/run_id charset."""
        pid = validate_run_id(program_id)
        return _write(self.root, community_dir(self.root) / "programs" / pid,
                      self.omx_dir / "programs" / pid)

    def program_json(self, program_id) -> Path:
        """programs/<program-id>/program.json (legacy) ->
        config/experiments/programs/<program-id>/program.json (new) — the
        machine-parsed header, split from program_dir()'s community/ narrative
        half per the mapping table."""
        pid = validate_run_id(program_id)
        return _write(self.root,
                      config_dir(self.root) / "programs" / pid / "program.json",
                      self.omx_dir / "programs" / pid / "program.json")

    def program_plan_md(self, program_id) -> Path:
        return self.program_dir(program_id) / "PLAN.md"

    def programs_root(self) -> tuple:
        """(new, legacy) programs root DIRECTORIES — for enumeration, over
        the community/ (narrative) layer program_dir() itself resolves to.
        NOT sufficient alone for list_programs(): a program whose only file
        is program.json under config/experiments/programs/<id>/ has no
        matching community/ entry yet, so list_programs() also scans
        config_dir(root) / "programs" directly (no legacy pairing needed
        there — legacy has no config/community split, and is already fully
        covered by this getter's legacy half)."""
        return (community_dir(self.root) / "programs", self.omx_dir / "programs")

    def runs_root(self) -> tuple:
        """(new, legacy) runs root DIRECTORIES — for enumeration, mirroring
        campaigns_root()."""
        return (work_dir(self.root) / "runs", self.omx_dir / "runs")

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
