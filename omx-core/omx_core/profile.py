"""omx_core.profile — Claude-free profile bootstrap (build #3).

exp-init (the Claude skill) runs the interview, then shells `omx init` which calls
bootstrap_profile() here. ALL profile schema validation + atomic file writes live
in this tested module (design D8: discipline enforced by code, not agent goodwill).
The skill writes nothing to .omx/profile/ directly.
"""
from __future__ import annotations

from omx_core.omx_paths import OmxError, Profile, validate_token

_KEEP_POLICIES = frozenset({"pass_only", "score_improvement"})
_VOCAB_FIELDS = ("metrics", "views", "aggs", "sources")


def validate_metrics_schema(data: dict) -> dict:
    """Validate a metrics.yaml dict (loud-fail OmxError); return it unchanged on success.

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
        Profile(run_id_regex=regex)

    policy = data.get("keep_policy")
    if policy not in _KEEP_POLICIES:
        raise OmxError(
            f"metrics.yaml: keep_policy must be one of {sorted(_KEEP_POLICIES)}, got {policy!r}")

    formula = data.get("score_formula", None)
    if policy == "score_improvement" and (not isinstance(formula, str) or formula == ""):
        raise OmxError(
            "metrics.yaml: score_formula is required (non-empty string) under "
            "keep_policy=score_improvement (B5: score-less candidates are discarded)")

    if data.get("pending_approval") is not True:
        raise OmxError(
            "metrics.yaml: pending_approval must be true on a freshly bootstrapped profile")

    return data
