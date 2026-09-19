"""Drift guard for `hooks/handlers.py::_STAGE_CLI_VERBS` (Ruling 35, task-8
fix-round-2). That constant is a hand-maintained MIRROR of "which `omx` CLI
verb is distinctive to which exp-* stage" -- derived once from the live
`omx_core.cli.build_parser()` cross-referenced against each stage's
`skills/<stage>/SKILL.md` body, per the team lead's instruction to read the
mapping from the source rather than invent it, and "put the mapping
somewhere a future verb addition will be noticed."

This test IS that notice: it recomputes the same distinctive-verb sets fresh
from build_parser() + the skill bodies and asserts they still equal the
constant. A verb added to a skill doc (or removed from the parser) without
updating `_STAGE_CLI_VERBS` fails this test loudly instead of the mapping
silently going stale -- exactly the failure class Finding 1 of this round
was: a fact recorded once and never re-checked against reality."""
import importlib.util
import re
from pathlib import Path

from omx_core.cli import build_parser

REPO = Path(__file__).resolve().parents[2]
HANDLERS_PATH = REPO / "hooks" / "handlers.py"
STAGES = ("exp-init", "exp-analyze", "exp-design", "exp-loop")


def _load_handlers():
    spec = importlib.util.spec_from_file_location(
        "omx_stage_cli_verbs_handlers", str(HANDLERS_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _all_live_verbs():
    """Every real `omx <verb>` (including nested `<group> <sub>` verbs like
    `wiki add`) straight from the live parser -- same enumeration shape
    test_skills_reference_real_verbs.py uses for the sibling drift guard."""
    p = build_parser()
    verbs = []
    for action in p._subparsers._group_actions:
        for name, sub in action.choices.items():
            nested = list(sub._subparsers._group_actions) if sub._subparsers else []
            if nested:
                for a2 in nested:
                    for n2 in a2.choices:
                        verbs.append(f"{name} {n2}")
            else:
                verbs.append(name)
    return verbs


def _recompute_distinctive_verbs():
    """For each stage, the live verbs its skills/<stage>/SKILL.md actually
    names as `omx <verb>`, restricted to verbs named in EXACTLY ONE stage's
    doc -- a verb shared across 2+ stages is a utility verb, not evidence of
    which specific stage is current (see _STAGE_CLI_VERBS's own comment)."""
    verbs = _all_live_verbs()
    per_stage = {}
    for stage in STAGES:
        body = (REPO / "skills" / stage / "SKILL.md").read_text(encoding="utf-8")
        per_stage[stage] = {v for v in verbs
                             if re.search(r"\bomx " + re.escape(v) + r"\b", body)}
    from collections import Counter
    counts = Counter()
    for vs in per_stage.values():
        counts.update(vs)
    return {stage: frozenset(v for v in vs if counts[v] == 1)
            for stage, vs in per_stage.items()}


def test_stage_cli_verbs_constant_matches_a_fresh_recomputation():
    handlers = _load_handlers()
    fresh = _recompute_distinctive_verbs()
    assert dict(handlers._STAGE_CLI_VERBS) == fresh, (
        "hooks/handlers.py::_STAGE_CLI_VERBS is stale -- a skill doc or the "
        "CLI parser changed the distinctive-verb set for at least one stage. "
        "Recompute and update the constant (see its comment for the method).")
