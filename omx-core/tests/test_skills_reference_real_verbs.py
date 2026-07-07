"""#25 — every `omx <verb>` a skill or agent references must be registered.

This is the guard that would have caught the pre-R2 drift where
exp-analyze/SKILL.md instructed `omx clean` while no such verb existed."""
import argparse
import re
from pathlib import Path

from omx_core.cli import build_parser

REPO = Path(__file__).resolve().parents[2]
_TOKEN = re.compile(r"\bomx\s+([a-z][a-z0-9-]*)(?:\s+([a-z][a-z0-9-]*))?")


def _registry():
    top = {}
    for a in build_parser()._actions:
        if isinstance(a, argparse._SubParsersAction):
            for name, sp in a.choices.items():
                subs = set()
                for b in sp._actions:
                    if isinstance(b, argparse._SubParsersAction):
                        subs |= set(b.choices)
                top[name] = subs
    return top


def test_skills_reference_real_verbs():
    registry = _registry()
    offenders = []
    files = sorted(list((REPO / "skills").rglob("SKILL.md"))
                   + list((REPO / "agents").glob("*.md")))
    assert files, "no skill/agent files found — wrong REPO anchor?"
    for md in files:
        for m in _TOKEN.finditer(md.read_text(encoding="utf-8")):
            verb, sub = m.group(1), m.group(2)
            if verb not in registry:
                offenders.append(f"{md.relative_to(REPO)}: omx {verb}")
            elif registry[verb] and sub is not None and sub not in registry[verb]:
                offenders.append(f"{md.relative_to(REPO)}: omx {verb} {sub}")
    assert not offenders, ("skills reference unregistered omx verbs:\n"
                           + "\n".join(offenders))
