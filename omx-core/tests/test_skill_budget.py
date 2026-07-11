"""#18 (D-R5-1): a pytest ceiling on skill-corpus size.

exp-analyze/SKILL.md accreted gates through 0.1.7->0.5.0 and loads whole into
context on every invocation; nothing guarded the growth. The contract:
  - per file  < 56 KiB (57,344 B)   — "real regression", not normal growth
  - corpus    < 128 KiB (131,072 B)
Skills are DISCOVERED BY GLOB (no hardcoded list) so a 5th skill is auto-covered.
Today max = exp-analyze ~44.6 KiB (~78% of ceiling), total ~87 KiB (66%): the
ceilings signal a real regression, not the next legitimate addition (critic F5).
Remedy on failure: split reference prose into a `references/` resource file the
skill reads on demand (the audit's sketch; the compaction machinery itself is NA
— there is no installer to run it)."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PER_FILE_CEILING = 57_344     # 56 KiB
TOTAL_CEILING = 131_072       # 128 KiB
KNOWN_SKILLS = {"exp-init", "exp-analyze", "exp-design", "exp-loop"}

REMEDY = ("split reference prose into a skills/<name>/references/ resource file "
          "read on demand (D-R5-1); do NOT reflexively bump the ceiling")


def _skill_files():
    return sorted((REPO / "skills").glob("*/SKILL.md"))


def test_glob_discovers_every_known_skill():
    # A vacuous pass is impossible: the glob MUST find exactly the known skills
    # (a broken anchor / empty glob fails here before the size asserts run).
    found = {p.parent.name for p in _skill_files()}
    assert found == KNOWN_SKILLS, f"skill glob drift: found {sorted(found)}"


def test_each_skill_under_per_file_ceiling():
    offenders = []
    for p in _skill_files():
        size = p.stat().st_size
        if size >= PER_FILE_CEILING:
            offenders.append(
                f"{p.relative_to(REPO)}: {size} B >= {PER_FILE_CEILING} B ceiling")
    assert not offenders, ("skill file(s) over the per-file ceiling:\n"
                           + "\n".join(offenders) + f"\nremedy: {REMEDY}")


def test_corpus_under_total_ceiling():
    total = sum(p.stat().st_size for p in _skill_files())
    assert total < TOTAL_CEILING, (
        f"skill corpus {total} B >= {TOTAL_CEILING} B ceiling\nremedy: {REMEDY}")


def test_ceiling_actually_bites(tmp_path):
    # Prove the per-file check is not a tautology: an oversize fixture MUST fail
    # the same predicate. This guards against a future edit that neuters the
    # comparison (e.g. flips >= to a no-op) without changing the real skills.
    big = tmp_path / "SKILL.md"
    big.write_bytes(b"x" * (PER_FILE_CEILING + 1))
    assert big.stat().st_size >= PER_FILE_CEILING
