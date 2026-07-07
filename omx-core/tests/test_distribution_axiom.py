"""D12 gate, mechanized (spec 2.11): the shipped surface carries no
workspace-specific identifier. The forbidden list lives HERE (tests are not
shipped surface); `isaaclab`/`rsl_rl` are allowed — public software names
(the committed reference profile is a shipped mechanism, not specialization)."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

FORBIDDEN = ("/workspace", "albc", "constrained_albc", "constrained-albc",
             "hero_agent", "marinelab", "bluerov", "isaac-constrainedalbc")


def _targets():
    yield from sorted((REPO / "omx-core" / "omx_core").rglob("*.py"))
    yield from sorted((REPO / "hooks").rglob("*.py"))
    yield from sorted((REPO / "skills").rglob("*.md"))
    yield from sorted((REPO / "agents").glob("*.md"))


def test_no_workspace_identifiers_in_shipped_surface():
    offenders = []
    for fp in _targets():
        low = fp.read_text(encoding="utf-8", errors="replace").lower()
        for tok in FORBIDDEN:
            if tok in low:
                for i, line in enumerate(low.splitlines(), 1):
                    if tok in line:
                        offenders.append(f"{fp.relative_to(REPO)}:{i}: {tok}")
    assert not offenders, ("D12 violation — workspace identifiers in the shipped "
                           "surface:\n" + "\n".join(offenders))
