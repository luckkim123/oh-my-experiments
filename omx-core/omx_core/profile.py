"""omx_core.profile — Claude-free profile bootstrap (build #3).

exp-init (the Claude skill) runs the interview, then shells `omx init` which calls
bootstrap_profile() here. ALL profile schema validation + atomic file writes live
in this tested module (design D8: discipline enforced by code, not agent goodwill).
The skill writes nothing to .omx/profile/ directly.
"""
from __future__ import annotations

import shutil

import yaml

from omx_core.omx_paths import (
    OmxError,
    OmxPaths,
    Profile,
    atomic_path,
    validate_token,
)

_KEEP_POLICIES = frozenset({"pass_only", "score_improvement"})
# ordered tuple (not a set) for deterministic error messages; all four always validated
_VOCAB_FIELDS = ("metrics", "views", "aggs", "sources")


def validate_metrics_schema(data: dict) -> dict:
    """Validate a FRESHLY-BOOTSTRAPPED metrics.yaml dict (loud-fail OmxError); return it unchanged on success.

    Enforces the schema locked in the build-#3 plan: output_root present;
    metrics/views/aggs/sources are non-empty token lists; run_id_regex null-or-
    compilable; keep_policy in {pass_only, score_improvement}; score_formula
    required under score_improvement (B5); pending_approval must be True when a
    profile is bootstrapped.
    """
    if not isinstance(data, dict):
        raise OmxError(f"metrics.yaml must parse to a mapping, got {type(data).__name__}")

    out_root = data.get("output_root")
    if not isinstance(out_root, str) or out_root == "":
        raise OmxError("metrics.yaml: output_root must be a non-empty string")

    for field in _VOCAB_FIELDS:
        seq = data.get(field)
        if not isinstance(seq, list) or len(seq) == 0:
            raise OmxError(f"metrics.yaml: {field} must be a non-empty list")
        for item in seq:
            # validate_token loud-fails on non-token (uppercase, '__', separators)
            validate_token(item, f"{field} entry")

    regex = data.get("run_id_regex", None)
    if regex is not None:
        # Construct a Profile so a bad pattern fails loud HERE (post_init compiles it).
        # Re-wrap so the error message is owned by profile.py, not omx_paths internals.
        try:
            Profile(run_id_regex=regex)
        except OmxError as e:
            raise OmxError(f"metrics.yaml: run_id_regex invalid: {e}") from e

    policy = data.get("keep_policy")
    if policy not in _KEEP_POLICIES:
        raise OmxError(
            f"metrics.yaml: keep_policy must be one of {sorted(_KEEP_POLICIES)}, got {policy!r}")

    formula = data.get("score_formula", None)
    if policy == "score_improvement" and (not isinstance(formula, str) or formula == ""):
        raise OmxError(
            "metrics.yaml: score_formula is required (non-empty string) under "
            "keep_policy=score_improvement (B5: score-less candidates are discarded)")

    # This validator runs only at bootstrap time; pending_approval=True is a
    # fresh-profile invariant (the approval workflow later flips it to false).
    if data.get("pending_approval") is not True:
        raise OmxError(
            "metrics.yaml: pending_approval must be true on a freshly bootstrapped profile")

    return data


RULES_TEMPLATE = """\
# Analysis discipline (consumed as guidance by exp-analyze)

## Always
- (e.g.) Report CV = std/mean for every metric; mean alone is half the picture.

## Never
- (e.g.) Assert "heavy-tail" without per-env peak counting.

## Notes
- (free form)
"""

LAUNCH_TEMPLATE = """\
#!/usr/bin/env bash
# OMX profile - training launch recipe. exp-loop (#6) QUEUES this as a
# 'pending approval' artifact; it is NEVER auto-fired (design D4/B8).
# Fill in your training command + GPU gate, then the human launches it.
set -euo pipefail

# GPU gate (example - adapt to your setup):
#   nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits

# Training command (placeholder - substitute your entrypoint; nothing machine-specific):
#   cd "$OMX_PROJECT_DIR" && python <your_train_entrypoint> --task "$OMX_TASK" ...
echo "launch.sh is a template; fill in your training command. exp-init never runs it."
"""

_METRICS_HEADER = (
    "# OMX profile - metrics vocabulary + output root.\n"
    "# Consumed by omx_paths.Profile (vocabulary tier) and exp-analyze (#4).\n"
    "# Set pending_approval to false (or delete the key) on approval.\n"
)


def default_metrics() -> dict:
    """The locked metrics.yaml schema with placeholder vocab — the interview fills it in."""
    return {
        "pending_approval": True,
        "output_root": "experiments",
        "metrics": ["ss_error", "attitude", "lin_vel", "survival_pct"],
        "views": ["trajectory", "per_axis_bar", "overlay"],
        "aggs": ["by_axis", "mean_std"],
        "sources": ["eval_summary"],
        "run_id_regex": None,
        "keep_policy": "pass_only",
        "score_formula": None,
    }


def load_profile(root) -> "Profile":
    """Read .omx/profile/metrics.yaml under `root` and build an omx_paths.Profile.

    Activates the B1 vocabulary tier for exp-analyze: metric/view/agg/source are
    drawn from the profile's closed vocab, run_id from its regex. Loud-fails if the
    profile is absent or its metrics.yaml lacks the vocab fields. Does NOT apply the
    bootstrap-only pending_approval invariant (an approved profile has cleared it).
    """
    paths = root if isinstance(root, OmxPaths) else OmxPaths(root=root)
    metrics_path = paths.profile_file("metrics.yaml")
    if not metrics_path.exists():
        raise OmxError(f"no profile at {metrics_path}; run exp-init first")
    data = yaml.safe_load(metrics_path.read_text())
    if not isinstance(data, dict):
        raise OmxError(f"metrics.yaml at {metrics_path} did not parse to a mapping")
    for field in _VOCAB_FIELDS:
        seq = data.get(field)
        if not isinstance(seq, list) or not seq:
            raise OmxError(f"metrics.yaml: {field} must be a non-empty list")
    return Profile(
        metrics=set(data["metrics"]),
        views=set(data["views"]),
        aggs=set(data["aggs"]),
        sources=set(data["sources"]),
        run_id_regex=data.get("run_id_regex"),
    )


def bootstrap_profile(paths: OmxPaths, *, profile_name: str = "isaaclab",
                      metrics: dict | None = None, force: bool = False) -> list:
    """Write the four .omx/profile/ files atomically; return the written Paths.

    Order is loud-fail-before-write: validate the schema and resolve the shipped
    reference evaluator FIRST, so an invalid profile or unknown reference leaves
    NO partial files (test_bootstrap_invalid_metrics_writes_nothing). Refuses to
    overwrite an existing profile unless force=True (a bootstrapped profile is the
    user's tuning - never silently clobbered; design 10.3 'profile is sacred').
    """
    metrics = default_metrics() if metrics is None else metrics
    validate_metrics_schema(metrics)                       # loud-fail #1 (before any write)
    reference = paths.reference_evaluator(profile_name)    # loud-fail #2 (missing reference)

    targets = {name: paths.profile_file(name)
               for name in ("evaluator.sh", "metrics.yaml", "rules.md", "launch.sh")}
    if not force:
        existing = [p for p in targets.values() if p.exists()]
        if existing:
            raise OmxError(
                f"profile already exists ({[p.name for p in existing]}); pass force=True "
                "to overwrite (profile is the user's tuning - never silently clobbered)")

    metrics_text = _METRICS_HEADER + yaml.safe_dump(metrics, sort_keys=True, default_flow_style=False)

    written = []
    with atomic_path(targets["evaluator.sh"]) as tmp:
        shutil.copyfile(reference, tmp)
    written.append(targets["evaluator.sh"])
    for name, text in (("metrics.yaml", metrics_text),
                       ("rules.md", RULES_TEMPLATE),
                       ("launch.sh", LAUNCH_TEMPLATE)):
        with atomic_path(targets[name]) as tmp:
            tmp.write_text(text)
        written.append(targets[name])
    return written
