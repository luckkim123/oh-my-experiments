"""skill-lint: structural FAIL-tier checks for skills/*/SKILL.md.

Scope (2026-07-20 triage of skill-lint-ci-design.md): only rules with 0
current violations across the 4 skill-bearing om* repos are enforced —
R1-R4 (frontmatter present, name == directory), R10 (references/<path>
existence), R11 (oms shim body-pointer resolves). Since nothing here
currently fails, there is no baseline/grandfather ledger — that machinery
is only needed to grandfather *existing* violations, and there are none.
The word-budget/description-convention WARN tiers and the om-core shared
extraction are out of scope for this pass (spec §7 decisions 1 and 5).
This file is a per-repo stdlib script (pathlib+re, zero deps), copied
identically into each repo's own tests/ so the existing `pytest` CI step
picks it up with zero ci.yml changes. (This repo's tests/ lives under
omx-core/, one level deeper than the other 3 repos — parents[2] instead of
parent.parent, matching the existing anchor in test_skill_budget.py.)

R1  SKILL.md has a --- ... --- YAML frontmatter fence.
R2  frontmatter `name:` present and non-empty.
R3  frontmatter `description:` present and non-empty.
R4  frontmatter `name:` == the skill's own directory name.
R10 every concrete `references/<path>` a skill body names exists on disk
    (placeholder tokens containing <>{}* are skipped — mirrors the
    verified pattern in test_skill_contract.py).
R11 a shim's `oms-full-body:` pointer, if present, resolves to an
    existing, non-empty file. No-op for skills that don't use the marker
    (only oh-my-scholar's shims do today; test_skill_shim.py already
    covers scholar's shim/body contract in full — this is a second,
    independent proof so the rule can't quietly rot into a no-op).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "skills"

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
REF_RE = re.compile(r"references/[A-Za-z0-9_\-./<>{}*]+")


def _skill_dirs():
    if not SKILLS_DIR.is_dir():
        return []
    return sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())


def _frontmatter(text):
    m = FRONTMATTER_RE.match(text)
    return m.group(1) if m else None


def _field(frontmatter, key):
    m = re.search(rf"^{key}:\s*(.*)$", frontmatter, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _concrete_refs(text):
    for m in REF_RE.finditer(text):
        path = m.group(0).rstrip(".,;:)")
        if any(ch in path for ch in "<>{}*"):
            continue
        yield path


def _frontmatter_violations(dirname, text):
    """R1-R3. Returns (violation messages, frontmatter block or None)."""
    fm = _frontmatter(text)
    if fm is None:
        return [f"{dirname}: no YAML frontmatter fence (R1)"], None
    violations = []
    if not _field(fm, "name"):
        violations.append(f"{dirname}: missing/empty 'name:' (R2)")
    if not _field(fm, "description"):
        violations.append(f"{dirname}: missing/empty 'description:' (R3)")
    return violations, fm


def _name_dir_violation(dirname, fm):
    """R4. fm may be None (already reported by R1)."""
    if fm is None:
        return None
    name = _field(fm, "name")
    if name and name != dirname:
        return f"{dirname}: name: {name!r} != directory {dirname!r} (R4)"
    return None


def _dangling_refs(dirname, text, root):
    """R10."""
    return [
        f"{dirname}: dangling reference {ref!r} (R10)"
        for ref in _concrete_refs(text)
        if not (root / ref).exists()
    ]


def _shim_pointer_violation(skill_dir, fm):
    """R11. fm may be None (already reported by R1); no-op if no shim marker."""
    if fm is None:
        return None
    pointer = _field(fm, "oms-full-body")
    if not pointer:
        return None
    body_path = (skill_dir / pointer).resolve()
    if not body_path.is_file():
        return f"{skill_dir.name}: oms-full-body points at missing file {pointer!r} (R11)"
    if body_path.stat().st_size == 0:
        return f"{skill_dir.name}: oms-full-body target {pointer!r} is empty (R11)"
    return None


# --- live checks against the real corpus -----------------------------------

def test_scan_targets_exist():
    # T1: a vacuous pass is impossible — a broken anchor must fail here,
    # not silently pass every rule below with zero skills scanned.
    assert _skill_dirs(), f"no skills/*/SKILL.md found under {SKILLS_DIR}"


def test_r1_r2_r3_frontmatter_required():
    offenders = []
    for d in _skill_dirs():
        v, _ = _frontmatter_violations(d.name, (d / "SKILL.md").read_text(encoding="utf-8"))
        offenders.extend(v)
    assert not offenders, "frontmatter violations:\n" + "\n".join(offenders)


def test_r4_name_matches_directory():
    offenders = []
    for d in _skill_dirs():
        text = (d / "SKILL.md").read_text(encoding="utf-8")
        _, fm = _frontmatter_violations(d.name, text)
        v = _name_dir_violation(d.name, fm)
        if v:
            offenders.append(v)
    assert not offenders, "name/directory mismatches:\n" + "\n".join(offenders)


def test_r10_references_paths_exist():
    offenders = []
    for d in _skill_dirs():
        text = (d / "SKILL.md").read_text(encoding="utf-8")
        offenders.extend(_dangling_refs(d.name, text, ROOT))
    assert not offenders, "dangling references/ paths:\n" + "\n".join(sorted(set(offenders)))


def test_r11_shim_body_pointer_resolves():
    offenders = []
    for d in _skill_dirs():
        text = (d / "SKILL.md").read_text(encoding="utf-8")
        _, fm = _frontmatter_violations(d.name, text)
        v = _shim_pointer_violation(d, fm)
        if v:
            offenders.append(v)
    assert not offenders, "shim body-pointer violations:\n" + "\n".join(offenders)


# --- meta-tests (T2): each FAIL rule must actually bite a fixture ----------
# Fixtures reuse the exact same check functions as the live tests above, so a
# future edit that neuters a check (e.g. a regex that stops matching) fails
# here even though the live corpus has nothing to trip over.

def _write_skill(tmp_path, dirname, content):
    skill_dir = tmp_path / "skills" / dirname
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


def test_meta_r1_missing_frontmatter_bites(tmp_path):
    d = _write_skill(tmp_path, "foo", "# no frontmatter fence\n")
    v, fm = _frontmatter_violations("foo", (d / "SKILL.md").read_text(encoding="utf-8"))
    assert fm is None
    assert any("R1" in x for x in v)


def test_meta_r2_missing_name_bites(tmp_path):
    d = _write_skill(tmp_path, "foo", "---\ndescription: x\n---\nbody\n")
    v, _ = _frontmatter_violations("foo", (d / "SKILL.md").read_text(encoding="utf-8"))
    assert any("R2" in x for x in v)


def test_meta_r3_missing_description_bites(tmp_path):
    d = _write_skill(tmp_path, "foo", "---\nname: foo\n---\nbody\n")
    v, _ = _frontmatter_violations("foo", (d / "SKILL.md").read_text(encoding="utf-8"))
    assert any("R3" in x for x in v)


def test_meta_r4_name_dir_mismatch_bites(tmp_path):
    d = _write_skill(tmp_path, "foo", "---\nname: bar\ndescription: x\n---\nbody\n")
    _, fm = _frontmatter_violations("foo", (d / "SKILL.md").read_text(encoding="utf-8"))
    v = _name_dir_violation("foo", fm)
    assert v and "R4" in v


def test_meta_r10_dangling_reference_bites(tmp_path):
    d = _write_skill(tmp_path, "foo", "---\nname: foo\ndescription: x\n---\nsee references/nope.md\n")
    text = (d / "SKILL.md").read_text(encoding="utf-8")
    offenders = _dangling_refs("foo", text, tmp_path)
    assert offenders and "R10" in offenders[0]


def test_meta_r10_placeholder_is_skipped(tmp_path):
    d = _write_skill(tmp_path, "foo", "---\nname: foo\ndescription: x\n---\nsee references/<format>.md\n")
    text = (d / "SKILL.md").read_text(encoding="utf-8")
    assert _dangling_refs("foo", text, tmp_path) == []


def test_meta_r11_missing_body_bites(tmp_path):
    d = _write_skill(
        tmp_path, "foo",
        "---\nname: foo\ndescription: x\noms-full-body: ../../skill-bodies/foo/SKILL.md\n---\nshim\n",
    )
    _, fm = _frontmatter_violations("foo", (d / "SKILL.md").read_text(encoding="utf-8"))
    v = _shim_pointer_violation(d, fm)
    assert v and "R11" in v


def test_meta_r11_empty_body_bites(tmp_path):
    d = _write_skill(
        tmp_path, "foo",
        "---\nname: foo\ndescription: x\noms-full-body: ../../skill-bodies/foo/SKILL.md\n---\nshim\n",
    )
    body_dir = tmp_path / "skill-bodies" / "foo"
    body_dir.mkdir(parents=True)
    (body_dir / "SKILL.md").write_text("", encoding="utf-8")
    _, fm = _frontmatter_violations("foo", (d / "SKILL.md").read_text(encoding="utf-8"))
    v = _shim_pointer_violation(d, fm)
    assert v and "R11" in v


def test_meta_r11_valid_pointer_passes(tmp_path):
    d = _write_skill(
        tmp_path, "foo",
        "---\nname: foo\ndescription: x\noms-full-body: ../../skill-bodies/foo/SKILL.md\n---\nshim\n",
    )
    body_dir = tmp_path / "skill-bodies" / "foo"
    body_dir.mkdir(parents=True)
    (body_dir / "SKILL.md").write_text("full body\n", encoding="utf-8")
    _, fm = _frontmatter_violations("foo", (d / "SKILL.md").read_text(encoding="utf-8"))
    v = _shim_pointer_violation(d, fm)
    assert v is None
