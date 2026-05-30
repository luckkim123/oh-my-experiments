# OMX build #5 — `exp-design` skill (+ core report parser) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `exp-design` skill that reads an exp-analyze `report.md`, runs a 3-lane differential diagnosis (code-path / config-DR-hyperparam / measurement-artifact), and writes a `pending approval` next-experiment proposal (the discriminating probe) into the permanent `proposals/` tree — plus the one Claude-free core helper it needs: a `report.md` finding parser.

**Architecture:** Two layers, matching the locked design boundary (core = IO/parsing, skill = judgment). (1) A new Claude-free `omx_core/report.py` parses the strict, line-oriented evidence tags (`[FINDING]` / `[EVIDENCE: ...]` / `[CONFIDENCE: ...]`) into structured `Finding` triplets, exposed as the `omx report-parse` CLI verb — unit-tested with no Claude, reused by exp-loop (#6). (2) `skills/exp-design/SKILL.md` is a thin Claude wrapper that calls `omx report-parse` for structured findings, performs the 3-lane diagnosis + discriminating-probe selection (pure judgment), and writes `proposals/<proposal_id>.md` through the EXISTING `proposal_md` getter + `atomic_path` (the exp-analyze heredoc pattern — no new path getter, no new write verb). Training launch is NEVER auto-fired (D4/B8): the proposal is an artifact a human approves.

**Tech Stack:** Python 3.12 (`python3`, not the Isaac `python` wrapper), pytest 9.x, stdlib `re`/`json`/`argparse` only (no new deps — parsing is regex over text). Skill is Markdown (Claude Code skill format).

**Design truth:** `docs/design/2026-05-30-omx-experiment-harness-design.md` §1 (trace row), §4/§4.1, §5 (router), §8 #5, §10.1 (proposals tree). Input contract = `skills/exp-analyze/SKILL.md` evidence-tag format. trace source verified at `marketplaces/omc/skills/trace/SKILL.md` (3 lanes lines 107-109; discriminating probe lines 42/73-75/259-262; evidence hierarchy line 56).

**Env traps (already burned — see HANDOFF.md):** `python3` not `python`. dist dir `omx-core/` (hyphen), import pkg `omx_core/` (underscore). `pip install -e .` needs `--break-system-packages`. Pyright `reportMissingImports(omx_core.*)` = editable false-positive, ignore. Run all pytest from `omx-core/` or with `cd /workspace/oh-my-experiments/omx-core`.

---

## File Structure

| File | Responsibility | Status |
|:--|:--|:--|
| `omx-core/omx_core/report.py` | **Create.** Claude-free parser: `Finding` dataclass + `parse_findings(text) -> list[Finding]` (regex triplet grouping, loud-fail on malformed/orphan tags). | new |
| `omx-core/omx_core/__init__.py` | **Modify.** Export `Finding`, `parse_findings`. | edit |
| `omx-core/omx_core/cli.py` | **Modify.** Add `_cmd_report_parse` + `report-parse` subparser (prints JSON array of findings; rc 0/2). | edit |
| `omx-core/tests/test_report.py` | **Create.** Unit tests for `parse_findings` (happy triplet, multiple findings, confidence levels, loud-fail on orphan/bad-confidence, empty). | new |
| `omx-core/tests/test_cli.py` | **Modify.** Add `report-parse` CLI tests (JSON shape, rc on bad file). | edit |
| `skills/exp-design/SKILL.md` | **Create.** The Claude skill: preconditions, read findings via `omx report-parse`, 3-lane diagnosis, discriminating-probe selection, write `proposals/<proposal_id>.md` via `proposal_md`+`atomic_path`, hard constraints (no launch). | new |
| `.claude-plugin/plugin.json` | **Modify.** Add `"./skills/exp-design/"` to `skills`. | edit |
| `docs/HANDOFF.md` | **Modify.** Mark #5 DONE, point NEXT at #6 exp-loop. | edit |

**Why a parser in core (not in the skill):** the user chose this (2026-05-30). The tags are strict-bracket, line-oriented, fixed-order (recon-confirmed) → deterministic regex parsing → Claude-free + unit-testable + reused by exp-loop (#6). Keeps the skill focused on judgment (which lane, which probe), which is the part Claude must do and cannot be unit-tested.

**Why NO new path getter / write verb:** `proposal_md(output_root, run_id, proposal_id)` already exists (`omx_paths.py:265`), `validate_proposal_id` already exists (alias of `validate_analysis_id`, allows `<TS>-<verb>`), and `atomic_path` already exists. exp-analyze established the heredoc-through-`atomic_path` pattern for writing a permanent-tree markdown file (SKILL.md:65-75). exp-design reuses it verbatim for the proposal. Adding a getter/verb would be YAGNI.

---

## Task 1: `Finding` dataclass + `parse_findings` (happy path)

**Files:**
- Create: `omx-core/omx_core/report.py`
- Test: `omx-core/tests/test_report.py`

The parser groups consecutive evidence tags into `Finding` triplets. A finding is a `[FINDING]` line, then exactly one `[EVIDENCE: ...]` line, then exactly one `[CONFIDENCE: HIGH|MED|LOW]` line, in that order. Non-tag lines (markdown prose, headings, image refs, blank lines) between findings are ignored. This task does the happy path; Task 2 adds loud-fail.

- [ ] **Step 1: Write the failing test**

Create `omx-core/tests/test_report.py`:

```python
from omx_core.report import Finding, parse_findings


def test_parse_single_triplet():
    text = (
        "## Analysis Results\n\n"
        "[FINDING] ss_error converged faster in run A than run B.\n"
        "[EVIDENCE: summary.json hard/roll/ss_error=0.21 vs 0.76]\n"
        "[CONFIDENCE: HIGH]\n"
    )
    out = parse_findings(text)
    assert len(out) == 1
    f = out[0]
    assert isinstance(f, Finding)
    assert f.claim == "ss_error converged faster in run A than run B."
    assert f.evidence == "summary.json hard/roll/ss_error=0.21 vs 0.76"
    assert f.confidence == "HIGH"


def test_parse_multiple_triplets_ignores_prose_and_images():
    text = (
        "# Report\n"
        "Some intro prose.\n\n"
        "[FINDING] Run B has a heavy tail in attitude error.\n"
        "[EVIDENCE: attitude__overlay.png shape, scratch plot]\n"
        "[CONFIDENCE: MED]\n\n"
        "![](plots/attitude__overlay.png)\n\n"
        "[FINDING] vx steady-state offset is within spec.\n"
        "[EVIDENCE: summary.json soft/vx/ss_error=0.009]\n"
        "[CONFIDENCE: HIGH]\n"
    )
    out = parse_findings(text)
    assert len(out) == 2
    assert out[0].confidence == "MED"
    assert out[1].claim == "vx steady-state offset is within spec."
    assert out[1].evidence == "summary.json soft/vx/ss_error=0.009"


def test_parse_empty_returns_empty_list():
    assert parse_findings("") == []
    assert parse_findings("# Just a heading\nno tags here\n") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_report.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.report'`.

- [ ] **Step 3: Write minimal implementation**

Create `omx-core/omx_core/report.py`:

```python
"""omx_core.report — parse exp-analyze report.md evidence tags (Claude-free).

exp-analyze writes findings as strict, line-oriented triplets (skills/exp-analyze
/SKILL.md, sciomc evidence-tag pattern):

    [FINDING] <one-line claim>
    [EVIDENCE: <source that proves it>]
    [CONFIDENCE: HIGH|MED|LOW]

Tags are bracket-anchored, never nested, and always appear in that fixed order.
That makes a pure regex parse deterministic and unit-testable — so it lives in
the core, not the skill. exp-design (#5) and exp-loop (#6) both read findings
through this. Malformed tag runs loud-fail (OmxError) rather than silently
dropping a finding (repo silent-fallback lesson).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from omx_core.omx_paths import OmxError

_FINDING = re.compile(r"\A\[FINDING\]\s*(.*\S)\s*\Z")
_EVIDENCE = re.compile(r"\A\[EVIDENCE:\s*(.*\S)\s*\]\Z")
_CONFIDENCE = re.compile(r"\A\[CONFIDENCE:\s*(HIGH|MED|LOW)\s*\]\Z")
# any line that opens with a known tag bracket (used to detect orphan/misordered tags)
_ANY_TAG = re.compile(r"\A\[(FINDING|EVIDENCE|CONFIDENCE)\b")


class ReportParseError(OmxError):
    """A report.md evidence-tag run is malformed (orphan/misordered/incomplete)."""


@dataclass(frozen=True)
class Finding:
    """One evidence-tagged finding from a report.md."""
    claim: str
    evidence: str
    confidence: str  # "HIGH" | "MED" | "LOW"


def parse_findings(text: str) -> list[Finding]:
    """Parse all [FINDING]/[EVIDENCE]/[CONFIDENCE] triplets from report.md text.

    Non-tag lines between triplets are ignored (prose, headings, image refs).
    Raises ReportParseError if a [FINDING] is not immediately followed (skipping
    nothing) by a matching [EVIDENCE] then [CONFIDENCE], or if an orphan
    [EVIDENCE]/[CONFIDENCE] appears with no open [FINDING]. (Task 2 fills these.)
    """
    findings: list[Finding] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        m = _FINDING.match(line)
        if not m:
            i += 1
            continue
        claim = m.group(1)
        ev = _EVIDENCE.match(lines[i + 1].strip()) if i + 1 < n else None
        cf = _CONFIDENCE.match(lines[i + 2].strip()) if i + 2 < n else None
        findings.append(Finding(claim=claim, evidence=ev.group(1), confidence=cf.group(1)))
        i += 3
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_report.py -q`
Expected: PASS (3 passed). (`ev`/`cf` are guaranteed non-None on the happy-path fixtures; Task 2 makes the missing case loud-fail instead of `AttributeError`.)

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/omx_core/report.py omx-core/tests/test_report.py
git commit -m "$(cat <<'EOF'
feat(report): parse_findings for exp-analyze evidence-tag triplets (happy path)

Claude-free parser of report.md [FINDING]/[EVIDENCE]/[CONFIDENCE] triplets into
Finding dataclasses. Core (not skill) per locked decision: tags are strict,
line-oriented, fixed-order -> deterministic + unit-testable, reused by #5/#6.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: loud-fail on malformed tag runs

**Files:**
- Modify: `omx-core/omx_core/report.py` (the `parse_findings` body from Task 1)
- Test: `omx-core/tests/test_report.py`

A `[FINDING]` with no following `[EVIDENCE]`/`[CONFIDENCE]`, a bad confidence keyword, or an orphan `[EVIDENCE]`/`[CONFIDENCE]` (no open finding) must raise `ReportParseError`, never silently drop the finding. This is the repo's silent-fallback lesson applied to parsing.

- [ ] **Step 1: Write the failing test**

Append to `omx-core/tests/test_report.py`:

```python
import pytest
from omx_core.report import ReportParseError


def test_finding_without_evidence_loud_fails():
    text = "[FINDING] dangling claim with no evidence line.\n"
    with pytest.raises(ReportParseError):
        parse_findings(text)


def test_finding_with_bad_confidence_keyword_loud_fails():
    text = (
        "[FINDING] claim.\n"
        "[EVIDENCE: src]\n"
        "[CONFIDENCE: PROBABLY]\n"  # not HIGH|MED|LOW
    )
    with pytest.raises(ReportParseError):
        parse_findings(text)


def test_orphan_evidence_tag_loud_fails():
    text = "[EVIDENCE: src with no finding above it]\n"
    with pytest.raises(ReportParseError):
        parse_findings(text)


def test_orphan_confidence_tag_loud_fails():
    text = "[CONFIDENCE: HIGH]\n"
    with pytest.raises(ReportParseError):
        parse_findings(text)


def test_finding_followed_by_prose_instead_of_evidence_loud_fails():
    text = (
        "[FINDING] claim.\n"
        "some prose that should have been an evidence tag\n"
        "[CONFIDENCE: HIGH]\n"
    )
    with pytest.raises(ReportParseError):
        parse_findings(text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_report.py -q`
Expected: FAIL — the new cases raise `AttributeError` (None.group) or pass silently / mis-parse, not `ReportParseError`.

- [ ] **Step 3: Write minimal implementation**

Replace the `while i < n:` body of `parse_findings` in `omx-core/omx_core/report.py` with:

```python
    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if _EVIDENCE.match(line) or _CONFIDENCE.match(line):
            raise ReportParseError(
                f"orphan evidence/confidence tag with no open [FINDING] at line {i + 1}: {line!r}")
        m = _FINDING.match(line)
        if not m:
            # plain prose / heading / image ref between findings — skip
            i += 1
            continue
        claim = m.group(1)
        ev_line = lines[i + 1].strip() if i + 1 < n else ""
        cf_line = lines[i + 2].strip() if i + 2 < n else ""
        ev = _EVIDENCE.match(ev_line)
        if not ev:
            raise ReportParseError(
                f"[FINDING] at line {i + 1} not followed by [EVIDENCE: ...] (got {ev_line!r})")
        cf = _CONFIDENCE.match(cf_line)
        if not cf:
            raise ReportParseError(
                f"[FINDING] at line {i + 1} not followed by a valid "
                f"[CONFIDENCE: HIGH|MED|LOW] (got {cf_line!r})")
        findings.append(Finding(claim=claim, evidence=ev.group(1), confidence=cf.group(1)))
        i += 3
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_report.py -q`
Expected: PASS (8 passed — 3 from Task 1 + 5 new). The Task 1 happy-path cases still pass (prose/image lines skip cleanly; valid triplets parse).

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/omx_core/report.py omx-core/tests/test_report.py
git commit -m "$(cat <<'EOF'
feat(report): loud-fail on malformed evidence-tag runs

A [FINDING] missing its [EVIDENCE]/[CONFIDENCE], a bad confidence keyword, or an
orphan tag raises ReportParseError instead of silently dropping the finding
(repo silent-fallback lesson). Happy path from Task 1 unaffected.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: export `Finding`/`parse_findings` + `omx report-parse` CLI verb

**Files:**
- Modify: `omx-core/omx_core/__init__.py:2-14`
- Modify: `omx-core/omx_core/cli.py` (add `_cmd_report_parse` near the other `_cmd_*`; add subparser in `build_parser`)
- Test: `omx-core/tests/test_cli.py`

The skill shells `omx report-parse --path <report.md>` and gets a JSON array of findings on stdout (rc 0). A missing file or a malformed report loud-fails (rc 2 via `SystemExit(str)`), matching the other verbs.

- [ ] **Step 1: Write the failing test**

Append to `omx-core/tests/test_cli.py`:

```python
def test_cli_report_parse_emits_json_findings(tmp_path, capsys):
    from omx_core.cli import main
    rpt = tmp_path / "report.md"
    rpt.write_text(
        "## Findings\n\n"
        "[FINDING] roll regressed at hard DR.\n"
        "[EVIDENCE: summary.json hard/roll/ss_error=0.76]\n"
        "[CONFIDENCE: HIGH]\n"
    )
    rc = main(["report-parse", "--path", str(rpt)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_findings"] == 1
    assert out["findings"][0]["claim"] == "roll regressed at hard DR."
    assert out["findings"][0]["evidence"] == "summary.json hard/roll/ss_error=0.76"
    assert out["findings"][0]["confidence"] == "HIGH"


def test_cli_report_parse_missing_file_rc2(tmp_path, capsys):
    from omx_core.cli import main
    rc = main(["report-parse", "--path", str(tmp_path / "nope.md")])
    assert rc == 2
    assert "not found" in capsys.readouterr().err.lower()


def test_cli_report_parse_malformed_rc2(tmp_path, capsys):
    from omx_core.cli import main
    rpt = tmp_path / "bad.md"
    rpt.write_text("[FINDING] dangling with no evidence.\n")
    rc = main(["report-parse", "--path", str(rpt)])
    assert rc == 2
    assert "evidence" in capsys.readouterr().err.lower()
```

(Note: `test_cli.py` already imports `json` and uses `capsys` in sibling tests — confirm the top-of-file imports include `import json`; it does.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_cli.py -k report_parse -q`
Expected: FAIL — `argument cmd: invalid choice: 'report-parse'`.

- [ ] **Step 3a: Implement the CLI command**

In `omx-core/omx_core/cli.py`, add this import alongside the others (after line 25):

```python
from omx_core.report import parse_findings
```

Add `_cmd_report_parse` after `_cmd_init` (before `_now_stamp`):

```python
def _cmd_report_parse(args) -> int:
    """Parse an exp-analyze report.md into structured findings (Claude-free).

    The exp-design skill (#5) shells this to read findings without re-implementing
    the tag grammar; exp-loop (#6) reuses it. rc 0 + JSON {n_findings, findings:[]}
    on success; rc 2 (SystemExit) on a missing file or a malformed tag run."""
    path = args.path
    if not os.path.exists(path):
        raise SystemExit(f"report not found: {path}")
    text = open(path, encoding="utf-8").read()
    try:
        findings = parse_findings(text)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps({
        "n_findings": len(findings),
        "findings": [
            {"claim": f.claim, "evidence": f.evidence, "confidence": f.confidence}
            for f in findings
        ],
    }))
    return 0
```

- [ ] **Step 3b: Register the subparser**

In `build_parser`, add after the `init` subparser block (after line 268, before `return p`):

```python
    prp = sub.add_parser("report-parse", help="parse exp-analyze report.md -> JSON findings (Claude-free)")
    prp.add_argument("--path", required=True, help="path to an exp-analyze report.md")
    prp.set_defaults(func=_cmd_report_parse)
```

- [ ] **Step 3c: Export from the package**

In `omx-core/omx_core/__init__.py`, add the import and `__all__` entries. Replace lines 2-14 with:

```python
from omx_core.omx_paths import (
    OmxPaths, Profile, OmxPathError,
    validate_analysis_id, validate_proposal_id, validate_session_id,
    validate_run_id, validate_token, validate_ext,
    resolve_session_id, atomic_path, atomic_dir,
)
from omx_core.report import Finding, parse_findings, ReportParseError

__all__ = [
    "OmxPaths", "Profile", "OmxPathError",
    "validate_analysis_id", "validate_proposal_id", "validate_session_id",
    "validate_run_id", "validate_token", "validate_ext",
    "resolve_session_id", "atomic_path", "atomic_dir",
    "Finding", "parse_findings", "ReportParseError",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_cli.py -k report_parse -q`
Expected: PASS (3 passed).

Then full suite + import-safety (the parser is stdlib-only, so the deferred-heavy-import guard must still pass):

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest -q`
Expected: PASS — previous count + 8 (Task 1/2) + 3 (Task 3) new = **289 passed, 1 skipped** (was 278/1).

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/omx_core/cli.py omx-core/omx_core/__init__.py omx-core/tests/test_cli.py
git commit -m "$(cat <<'EOF'
feat(cli): omx report-parse — report.md findings to JSON (Claude-free)

The exp-design skill shells this to read structured findings without re-coding the
tag grammar; rc 0 + {n_findings, findings:[]} on success, rc 2 on missing/malformed
report. Exports Finding/parse_findings/ReportParseError from omx_core.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `exp-design` skill — preconditions + read findings

**Files:**
- Create: `skills/exp-design/SKILL.md`

This task writes the skill's front-matter, overview, preconditions, and the "read the analysis" section. Tasks 5-6 add the diagnosis and the proposal write. The skill is Markdown; the "test" is that an implementer/reviewer can read it and execute the steps unambiguously against the real core, and that the front-matter is valid skill format matching the exp-analyze/exp-init siblings.

- [ ] **Step 1: Create the skill skeleton (front-matter + overview + preconditions + read-findings)**

Create `skills/exp-design/SKILL.md`:

````markdown
---
name: exp-design
description: Design the next experiment from an exp-analyze report. Use after analyzing runs, when you need to decide what to change next — runs a 3-lane differential diagnosis (code-path / config-DR-hyperparam / measurement-artifact) over the evidence-tagged findings and proposes the single discriminating probe (the next-experiment config) as a pending-approval artifact. Reads report.md, writes proposals/<id>.md. Never launches training or eval. Triggers on "design the next experiment", "what should I change next", "diagnose why this regressed and propose a fix experiment", "다음 실험 설계", "다음에 뭘 바꿔야 할까".
argument-hint: "[--root <dir>] <path to an exp-analyze report.md, or run id + analysis id>"
---

# exp-design — 3-lane differential diagnosis → discriminating probe (next experiment)

## Overview

`exp-design` turns an exp-analyze `report.md` into the NEXT experiment. It runs a
differential diagnosis across three competing hypothesis lanes (design §1, OMC
trace pattern), picks the single **discriminating probe** — the cheapest change
whose outcome the top two hypotheses predict differently — and writes that probe
as a `pending approval` proposal in the permanent `proposals/` tree.

It NEVER launches training or eval (design D4/B8). The proposal is an artifact a
human reads and approves; exp-design's job ends at writing it.

**Announce at start:** "Using exp-design to diagnose the findings and propose the next experiment."

## Preconditions (check, don't assume)

1. A profile exists and is approved. Read `<root>/.omx/profile/metrics.yaml`. Missing
   → tell the user to run exp-init first; STOP. `pending_approval: true` still set
   → tell the user to approve it first; STOP. (Honors the exp-init hard gate.)
2. An exp-analyze `report.md` exists. The user gives either a direct path to a
   `report.md`, or a `<run_id>` + `<analysis_id>` from which you resolve it with
   `omx_paths.report_md(output_root, run_id, analysis_id)` (output_root from the
   profile's metrics.yaml). If the report is missing, say so and STOP — never
   invent findings.

## Step 1 — read the structured findings (via the core, never re-parse by hand)

Get the findings as JSON from the Claude-free parser; do NOT eyeball the markdown
for `[FINDING]` lines yourself (the parser is the contract, and it loud-fails on a
malformed report — which is a signal the report is broken, not something to paper over):

```bash
omx report-parse --path "<output_root>/<run_id>/analysis/<analysis_id>/report.md"
```

This prints `{"n_findings": N, "findings": [{"claim","evidence","confidence"}, ...]}`.
If it exits non-zero, the report is malformed — report that to the user and STOP;
do not hand-parse around it.

Also read the report.md prose yourself (with the Read tool) for the narrative
context the tags don't carry (what was compared, the baseline, the user's
question). The tags give you the structured claims; the prose gives you intent.
````

- [ ] **Step 2: Verify front-matter validity + sibling consistency**

Run:
```bash
cd /workspace/oh-my-experiments
head -6 skills/exp-design/SKILL.md
head -6 skills/exp-analyze/SKILL.md
```
Expected: exp-design front-matter has the same keys as exp-analyze (`name`, `description`, `argument-hint`), `name: exp-design`, triggers include both EN + KO phrases. Visually confirm the YAML opens/closes with `---`.

- [ ] **Step 3: Verify the referenced core surface exists (no dangling references)**

Run:
```bash
cd /workspace/oh-my-experiments/omx-core
python3 -c "from omx_core import parse_findings; from omx_core.omx_paths import OmxPaths; print(OmxPaths(root='.').report_md.__doc__ is not None or 'ok')"
python3 -m omx_core.cli report-parse --help | head -3
```
Expected: no ImportError; `report-parse` help prints. (Confirms the skill's `omx report-parse` + `report_md` references are real before we build the diagnosis on top.)

- [ ] **Step 4: Commit**

```bash
cd /workspace/oh-my-experiments
git add skills/exp-design/SKILL.md
git commit -m "$(cat <<'EOF'
feat(exp-design): skill skeleton — front-matter, preconditions, read findings

Front-matter + overview + preconditions + Step 1 (read findings via omx
report-parse, never hand-parse). Diagnosis + proposal-write land in the next tasks.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `exp-design` skill — the 3-lane differential diagnosis (core IP)

**Files:**
- Modify: `skills/exp-design/SKILL.md` (append the diagnosis section)

This is the heart of #5. It re-implements OMC trace's 3-lane model (verified
`trace/SKILL.md:107-109`) as an explicit procedure the skill follows: for each
lane, gather evidence FOR/AGAINST from the findings, name the critical unknown,
and name that lane's candidate probe; then rank and pick the single discriminating
probe across lanes (`trace/SKILL.md:42,73-75,259-262`).

- [ ] **Step 1: Append the diagnosis section to `skills/exp-design/SKILL.md`**

Append:

````markdown
## Step 2 — 3-lane differential diagnosis (the core IP, design §1 / OMC trace pattern)

You have the structured findings + the report prose. Now diagnose WHY the result
is what it is, by competing hypotheses across three lanes. This mirrors OMC's
trace skill (3 lanes; evidence for/against; critical unknown; discriminating
probe). Apply the repo's own discipline: differential diagnosis first (a cause
that hits one channel but not another is the strongest clue), never a generic
"schedule/curriculum/adaptive" guess without evidence.

For EACH of the three lanes, write a short block:

1. **Code-path / implementation lane.** Hypothesis: the result is caused by the
   model/algorithm/reward/constraint code itself (a function does not do what its
   name says; a path is only exercised by some axes). Evidence FOR / AGAINST drawn
   from the findings + prose. Critical unknown. Candidate probe.
2. **Config / DR / hyperparameter lane.** Hypothesis: the result is caused by a
   config value — DR range/curriculum, a hyperparameter, an env setting, ocean
   current, a seed. Evidence FOR / AGAINST. Critical unknown. Candidate probe.
3. **Measurement / artifact lane.** Hypothesis: the result is not a real
   regression at all — it is an eval/measurement artifact (sample-env divergence
   vs heavy-tail confusion; wrong eval mode; output-naming/path mix-up; aggregation
   that hides per-env variance). Evidence FOR / AGAINST. Critical unknown.
   Candidate probe.

Rules while diagnosing:
- Rank evidence by strength (strongest → weakest): controlled reproduction / a
  uniquely discriminating artifact > a primary artifact with tight provenance
  (an exact metric from summary.json, a code file:line) > multiple independent
  sources agreeing > single-source inference > weak circumstantial (naming,
  timing) > speculation. A `[CONFIDENCE: HIGH]` finding with a code-exec number
  outranks a `[CONFIDENCE: MED]` inference.
- A finding's `confidence` tag is an input, not the verdict: a HIGH-confidence
  measurement can still SUPPORT the measurement-artifact lane (it proves a number,
  not its cause).
- Do NOT pre-commit to a lane. The point is to let evidence separate them. If two
  lanes fit equally, that IS the finding — and the probe must be the test that
  splits them.

## Step 3 — pick the single discriminating probe (= the next experiment)

From the three lanes, identify the leading hypothesis and the strongest remaining
alternative. The **discriminating probe** is the cheapest next experiment whose
outcome those two predict DIFFERENTLY (OMC trace: "the highest-value next step to
collapse uncertainty", "the cheapest probe that would discriminate it from the
next-best alternative"). State, explicitly:

- **What each top hypothesis predicts** the probe's outcome would be (they must
  differ — if they predict the same thing, the probe does not discriminate; pick
  another).
- **The exact change** the probe makes: which single config value / code path /
  measurement method changes, and to what. Honor the repo "minimum-change" rule:
  change ONE variable so the next run is not confounded.
- **What result confirms which hypothesis.**

The discriminating probe, expressed as a concrete change to the training/eval
setup, IS the proposed next experiment. It is a PROPOSAL — never run it.
````

- [ ] **Step 2: Self-check the diagnosis section against the trace source**

Verify the three lanes match the trace source and the design lanes:

Run:
```bash
grep -n "Code-path / implementation cause\|Config / environment / orchestration cause\|Measurement / artifact / assumption mismatch cause" /root/.claude/plugins/marketplaces/omc/skills/trace/SKILL.md
```
Expected: the three lane names print (lines ~107-109). Confirm the skill's three lanes are the same three (code-path / config-DR-hyperparam / measurement-artifact) — names adapted to the experiment domain per design §1 but 1:1 with trace.

- [ ] **Step 3: Commit**

```bash
cd /workspace/oh-my-experiments
git add skills/exp-design/SKILL.md
git commit -m "$(cat <<'EOF'
feat(exp-design): 3-lane differential diagnosis + discriminating-probe selection

The core IP: re-implements OMC trace's 3-lane model (code-path / config-DR-hyperparam
/ measurement-artifact) with evidence FOR/AGAINST + critical unknown per lane, then
picks the single cheapest probe the top two hypotheses predict differently = the next
experiment. Minimum-change rule enforced (one variable).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `exp-design` skill — write the proposal + hard constraints

**Files:**
- Modify: `skills/exp-design/SKILL.md` (append the write section + constraints + when-done)

The proposal is written through the EXISTING `proposal_md` getter + `atomic_path`
(the exp-analyze heredoc pattern, SKILL.md:65-75). `proposal_id` = `<YYYYMMDD-HHMMSS>-next`
(design §10.1; `validate_proposal_id` allows it). No new core code.

- [ ] **Step 1: Append the write section + constraints to `skills/exp-design/SKILL.md`**

Append:

````markdown
## Step 4 — write the proposal (permanent tree, via the core — never hand-write paths)

1. Choose a `proposal_id` = `<YYYYMMDD-HHMMSS>-next` (the verb is literally `next`,
   matching design §10.1). Get the timestamp from `date +%Y%m%d-%H%M%S` via Bash.
2. Resolve `output_root` from the profile's `metrics.yaml` (the same value
   exp-analyze used) and the `run_id` (the run the analysis was about).
3. Draft the proposal markdown. It MUST contain, in order:
   - **`# Next-experiment proposal — pending approval`** heading, with the
     `run_id`, source `analysis_id`, and the `proposal_id`.
   - **`## Diagnosis`** — the three lane blocks (code-path / config-DR-hyperparam /
     measurement-artifact), each with evidence FOR/AGAINST and its critical unknown,
     ending with the ranked leading hypothesis vs strongest alternative.
   - **`## Discriminating probe (the proposed change)`** — what each top hypothesis
     predicts, the single-variable change (with exact value), and what result
     confirms which hypothesis.
   - **`## How to run (for the human — NOT auto-executed)`** — the concrete command
     delta from the profile's `launch.sh` (e.g. "set `payload_cog_offset_xy_radius`
     0.08 → 0.05, all else identical to <baseline run>"). State plainly that
     exp-design did NOT launch it.
   - **`## Status: pending approval`** — the hard gate. The human must approve
     before any run.
   - Keep every numeric claim traceable to a finding's evidence (carry the
     `[EVIDENCE: ...]` source through). No new numbers you did not get from the
     report / code-exec.
4. Write it into the permanent tree THROUGH the core's atomic writer so the path
   comes from the getter AND the proposals dir is created:

   ```bash
   python3 - <<'PY'
   from omx_core.omx_paths import OmxPaths, atomic_path
   p = OmxPaths(root="<root>").proposal_md("<output_root>", "<run_id>", "<proposal_id>")
   with atomic_path(p) as tmp:
       tmp.write_text(r"""<the full proposal markdown you assembled>""")
   print(p)
   PY
   ```

## Hard constraints (never violate)

- NEVER launch training or eval. exp-design only WRITES a proposal. No `launch.sh`,
  no live eval_dr, no `omx eval` against a live run. (design D4/B8 — the repo rule
  "훈련 종료/시작은 유저가 직접" has no override path here.)
- NEVER write a path by hand; the proposal path comes from `proposal_md(...)` and
  the write goes through `atomic_path`. `proposal_id` = `<YYYYMMDD-HHMMSS>-next`.
- NEVER invent a finding or a number. Every claim traces to a `report.md` finding
  (read via `omx report-parse`) or its `[EVIDENCE: ...]` source. If the report has
  no finding supporting a lane, say that lane is unsupported — do not manufacture one.
- The probe changes ONE variable (repo minimum-change rule) so the next run is not
  confounded.
- Respond to the user in Korean (repo rule); keep the proposal markdown / code in English.

## When done

Tell the user where the proposal is
(`<output_root>/<run_id>/proposals/<proposal_id>.md`), summarize the leading
hypothesis and the one-variable probe in 2-3 lines, and remind them it is
**pending approval — not launched**. Do not start a loop or run anything; the
analyze→design→eval loop is exp-loop's job (#6).
````

- [ ] **Step 2: End-to-end dry verification of the write path**

Confirm the heredoc write path works against the real core (no profile needed —
structural tier), exactly as the skill instructs, then clean up:

Run:
```bash
cd /workspace/oh-my-experiments/omx-core && python3 - <<'PY'
import tempfile, os
from omx_core.omx_paths import OmxPaths, atomic_path
d = tempfile.mkdtemp()
out = os.path.join(d, "experiments")
p = OmxPaths(root=d).proposal_md(out, "r13_teacher", "20260530-235959-next")
with atomic_path(p) as tmp:
    tmp.write_text("# Next-experiment proposal — pending approval\n## Status: pending approval\n")
assert p.exists(), p
print("OK", p)
PY
```
Expected: `OK .../experiments/r13_teacher/proposals/20260530-235959-next.md` — confirms `proposal_md` + `atomic_path` create the proposals dir and write atomically, with no new core code.

- [ ] **Step 3: Commit**

```bash
cd /workspace/oh-my-experiments
git add skills/exp-design/SKILL.md
git commit -m "$(cat <<'EOF'
feat(exp-design): write pending-approval proposal + hard constraints

Proposal written via existing proposal_md getter + atomic_path (exp-analyze
pattern, no new core). proposal_id=<TS>-next. Hard gate: never launches training/
eval, one-variable change, every number traces to a report finding. Verified the
heredoc write path creates proposals/ atomically.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: register the skill in plugin.json + HANDOFF

**Files:**
- Modify: `.claude-plugin/plugin.json` (the `skills` array)
- Modify: `docs/HANDOFF.md`

- [ ] **Step 1: Add exp-design to plugin.json**

Edit `.claude-plugin/plugin.json` — change the `skills` array from:

```json
  "skills": [
    "./skills/exp-init/",
    "./skills/exp-analyze/"
  ]
```

to:

```json
  "skills": [
    "./skills/exp-init/",
    "./skills/exp-analyze/",
    "./skills/exp-design/"
  ]
```

- [ ] **Step 2: Verify plugin.json is valid JSON**

Run:
```bash
cd /workspace/oh-my-experiments
python3 -c "import json; d=json.load(open('.claude-plugin/plugin.json')); assert d['skills']==['./skills/exp-init/','./skills/exp-analyze/','./skills/exp-design/'], d['skills']; print('ok', d['skills'])"
```
Expected: `ok ['./skills/exp-init/', './skills/exp-analyze/', './skills/exp-design/']`.

- [ ] **Step 3: Update HANDOFF.md**

In `docs/HANDOFF.md`, add a `#5 exp-design — DONE` bullet next to the `#4 exp-analyze — DONE` bullet (around line 45), summarizing: core `report.py`/`parse_findings` + `omx report-parse` verb (Claude-free, loud-fail), `skills/exp-design/SKILL.md` (3-lane diagnosis → discriminating probe → `proposals/<id>.md` pending-approval, no launch), plugin.json now 3 skills, test count. Mark `NEXT = #6 exp-loop`. (Edit the existing #4 bullet's trailing `NEXT = #5 exp-design` to point at #6.)

- [ ] **Step 4: Run the full suite one final time**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest -q`
Expected: **289 passed, 1 skipped** (no regressions from the doc/plugin edits).

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add .claude-plugin/plugin.json docs/HANDOFF.md
git commit -m "$(cat <<'EOF'
feat(plugin): register exp-design skill; HANDOFF #5 done

plugin.json skills now [exp-init, exp-analyze, exp-design]. HANDOFF marks #5 done
(core report parser + exp-design diagnosis skill), NEXT = #6 exp-loop.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## FINAL: opus cross-cutting review + finish

- [ ] **Step 1: Dispatch a final opus reviewer** over the whole #5 diff (`git diff main...HEAD` on the feature branch, or `git log --oneline` of the #5 commits). Review lenses:
  1. **Boundary integrity** — is the parser genuinely Claude-free (no judgment baked in)? Is all the diagnosis judgment in the skill (not the core)? Does the skill hand-write any path or hand-parse any tag (it must not)?
  2. **trace fidelity** — do the 3 lanes + discriminating-probe rule faithfully match `trace/SKILL.md` (lanes 107-109, probe 42/73-75/259-262, evidence hierarchy 56) AND design §1/§5?
  3. **Hard-gate** — is there ANY path where exp-design launches training/eval? (must be none — grep the skill for launch/eval verbs.) Is `pending approval` present and prominent?
  4. **Input contract** — does the skill read findings only via `omx report-parse`, and does the parser loud-fail (not silently drop) on a malformed report?
  5. **Repo discipline** — minimum-change (one variable) probe; every number traceable; Korean-to-user / English-in-artifacts; no AI-attribution in shipped content (git trailer is the only allowed exception); no absolute paths / private repo names in the shipped skill (placeholders only).
  Report Critical/Important/Minor with file:line. Fix Critical + Important before finishing.

- [ ] **Step 2: Apply any Critical/Important fixes** the reviewer finds (fresh implementer if non-trivial), re-run `python3 -m pytest -q` (expect 289/1), re-commit.

- [ ] **Step 3: Use `superpowers:finishing-a-development-branch`.** Verify tests pass, present the 4 options. **Do NOT push or merge until the user explicitly authorizes** (repo rule: push only on explicit request; build cadence: #5 stops at a finished local branch unless the user greenlights merge/push). Default expectation: merge to local `main` only if the user says so; otherwise keep the branch and report it ready.

---

## Self-Review (run before handing off — writing-plans checklist)

**1. Spec coverage (design §4 exp-design row + §1 trace row + §10.1 proposals tree):**
- exp-design role "trace 3-lane → discriminating-probe" → Tasks 4-6 (read findings / diagnose / write probe). ✓
- output `<output_root>/<run_id>/proposals/<proposal_id>.md` pending approval → Task 6 (proposal_md + atomic_path, `<TS>-next`, Status: pending approval). ✓
- input = exp-analyze report.md evidence tags → Tasks 1-3 (core parser) + Task 4 Step 1 (skill reads via `omx report-parse`). ✓
- "training launch NEVER auto-fired" (D4/B8) → Task 6 hard constraints + FINAL review lens 3. ✓
- core stays Claude-free / skill is the Claude judgment (H3) → parser in core (Tasks 1-3), diagnosis in skill (Tasks 4-6); user-confirmed boundary. ✓
- plugin.json registration → Task 7. ✓
- proposal getter "확인 — 있으면 재사용" (NEXT-PROMPT) → confirmed existing (`omx_paths.py:265`), reused, no new getter. ✓

**2. Placeholder scan:** no "TBD/TODO/handle edge cases/similar to Task N". Every code step shows full code; every skill step shows the full markdown block; every command has an expected result. ✓

**3. Type consistency:** `Finding(claim, evidence, confidence)` defined Task 1, used identically in Tasks 1/2/3 (CLI emits `{claim,evidence,confidence}`) and referenced by the skill's `omx report-parse` JSON shape (Task 4). `parse_findings(text) -> list[Finding]` signature stable across Tasks 1-3. `ReportParseError(OmxError)` defined Task 1, raised Task 2, caught as `OmxError` in the CLI (Task 3). `proposal_md(output_root, run_id, proposal_id)` + `atomic_path` are existing core signatures (verified `omx_paths.py:265,310`), used unchanged in Task 6. Test count arithmetic: 278→+8(T1/T2)→+3(T3)=289 consistently in Task 3 Step 4 and Task 7 Step 4. ✓

No gaps found.
