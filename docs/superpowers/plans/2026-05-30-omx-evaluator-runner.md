# OMX Build-Order #2 — Evaluator-Contract Runner + Isaac Lab Reference Profile

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the autoresearch evaluator-contract layer in `omx-core` — a pure-Python re-implementation of OMC's `{pass, score?}` evaluator contract + keep-policy decision tree + the 3-artifact ledger trio with B6 hybrid-revert pointer mechanics, plus a committed Isaac Lab reference evaluator and a Claude-free `omx eval` CLI verb.

**Architecture:** Five new modules under `omx-core/omx_core/` (`evaluator.py`, `decision.py`, `ledger.py`, `reference/`), all routing paths through the existing `omx_paths.py` SSOT (which gains 3 new getters + an `OmxError` base). The OMC TypeScript sources (`contracts.ts`, `runtime.ts`) are re-implemented branch-for-branch in Python and **never imported** (design D1). The whole layer is the Claude-free, Bash-unit-testable subset (design §4/§8): every test uses a fake shell evaluator (echo/printf/true/exit/sleep) — zero eval_dr, Isaac Sim, or network dependency.

**Tech Stack:** Python 3.12 (run with `python3`, NOT `python` — that is an Isaac Sim wrapper), stdlib `subprocess`/`json`/`datetime`, pytest 9.x. No new dependencies (stays within numpy/pandas/matplotlib/pyyaml). `pip install -e` needs `--break-system-packages` (PEP 668, root Docker).

**Source of truth:** `docs/design/2026-05-30-omx-experiment-harness-design.md` §8 item 2, §0.1 (B4/B5/B6), §1 (patterns to re-implement). OMC reference: `/root/.claude/plugins/marketplaces/omc/src/autoresearch/{contracts.ts,runtime.ts}`.

**Review provenance:** This plan was drafted then adversarially reviewed across 4 lenses (contract-fidelity, omx-core-convention, TDD-rigor, B6-revert-correctness) — all returned SOUND. Three IMPORTANT findings are folded in: (1) `baseline_commit` seeded at run-init and held invariant (NOT derived from first keep); (2) explicit non-keep-status pointer-leave test; (3) Task 1's reference-resolves test is strictly testable (loud-fail-when-absent now, strict-resolves in Task 6) — no self-weakening mid-task test.

---

## File Structure

All paths absolute under `/workspace/oh-my-experiments/`. New code in `omx-core/omx_core/`, tests in `omx-core/tests/`. Work on branch `feat/omx-evaluator` off `main` (currently `e219c1f`, **160 tests green**).

**NEW FILES:**
- `omx-core/omx_core/evaluator.py` — `parse_evaluator_result(raw)->dict` (loud-fail contract parser, re-impl of `contracts.ts:178-201`) + `run_evaluator(command, cwd, *, timeout=600)->dict` (subprocess; LAST non-empty stdout line; fault-tolerant-by-recording, re-impl of `runtime.ts:586-636`). Defines `EvaluatorError(OmxError)`. *(Deliverable 1)*
- `omx-core/omx_core/decision.py` — `parse_keep_policy(raw)->str` (case-insensitive, loud-fail, default `score_improvement`) + `decide_outcome(keep_policy, last_kept_score, evaluation)->dict` (exhaustive keep/discard/ambiguous/bootstrap tree, re-impl of `runtime.ts:665-763` + `comparableScore` 661-663). B5 coupling. *(Deliverables 2, 7)*
- `omx-core/omx_core/ledger.py` — the autoresearch 3-artifact trio writers (`append_results_row`, `append_ledger_entry`, `append_decision_log`) + `seed_ledger(...)` (B6 baseline anchor) + `record_iteration(...)` (writes all three + applies the B6 pointer rule). All via `omx_paths` getters + atomic writes. *(Deliverables 3, 4)*
- `omx-core/omx_core/reference/__init__.py` — marks `reference` an importable subpackage so its data files ship with the package.
- `omx-core/omx_core/reference/isaaclab/evaluator.sh` — COMMITTED Isaac Lab reference evaluator (ships `pass_only`); honest documented stub emitting a contract-valid `{"pass": ...}` last line, with the live-eval_dr slot shown in comments. *(Deliverable 5)*
- Tests: `test_evaluator.py`, `test_decision.py`, `test_ledger.py`, `test_reference_evaluator.py` (one per source); APPEND to `test_omx_paths.py` and `test_cli.py`.

**MODIFIED FILES:**
- `omx-core/omx_core/omx_paths.py` — ADD (Task 1, failing-test-first):
  - `OmxError(Exception)` base; reparent `OmxPathError(OmxError, ValueError)` (keeps existing `except ValueError` sites; makes `EvaluatorError(OmxError)` a sibling).
  - `reference_dir` property → packaged `omx_core/reference/` (anchored to `Path(__file__)`, NOT under `self.root`).
  - `reference_evaluator(profile_name)` → `reference/<profile>/evaluator.sh`; validates token; loud-fail if the shipped file is absent.
  - `checkpoint_pointer_json(run_id)` → `runs/<run_id>/checkpoint-pointer.json` (B6 weights-pointer mirror).
  - (Existing `run_dir`/`results_tsv`/`ledger_json`/`decision_log`/`state_json` reused unchanged.)
- `omx-core/omx_core/cli.py` — register `omx eval` verb (`_cmd_eval` returning int, `set_defaults(func=...)`). *(Deliverable 6)*
- `omx-core/pyproject.toml` — `[tool.setuptools.package-data]` to ship `reference/**/*.sh` on non-editable installs.

**No path is string-concatenated** — every `.omx` path comes from an `OmxPaths` getter; the reference path is package-anchored but still surfaced through a single getter.

---

## Locked Decisions (resolved in this plan)

**D1 — B6 ledger schema (LOCKED).** `ledger.json` top object:
```json
{"schema_version": 1,
 "baseline_commit":      "<sha|null>",   // pre-experiment anchor (config git-revert target). SEEDED at run-init, INVARIANT across keeps/discards.
 "last_kept_commit":     "<sha|null>",   // config pointer; ADVANCES on keep
 "last_kept_score":      "<number|null>",// score_improvement baseline; advances on numeric-score keep, else leave-prior
 "last_kept_checkpoint": "<path|null>",  // WEIGHTS pointer; ADVANCES on keep, LEAVES on non-keep, NEVER a git/rm op
 "entries": [ {iteration, decision, decision_reason, candidate_checkpoint, candidate_commit, evaluator, notes, description}, ... ]}
```
A standalone `checkpoint-pointer.json` mirrors `last_kept_checkpoint` so exp-loop (#6) reads the weights pointer without parsing the whole ledger. **The two are written as two sequential atomic writes; the ledger is authoritative** (the mirror may transiently lag on crash — #6 treats the ledger as source of truth). RULE (code+tests): keep → both ledger pointer and mirror advance to the candidate's checkpoint; discard/ambiguous/noop/abort/interrupted/error → both LEFT untouched; **NEVER a git/`rm` op on any weight file** (only the pointer string moves). Physical checkpoint GC is exp-loop's (#6) job, explicitly OUT of scope here.

> **Correction vs first draft (b6-revert review):** `baseline_commit` is the *pre-experiment* anchor — the point a config revert unwinds TO. It is seeded ONCE at run-init via `seed_ledger(...)` and is **invariant**. It is NOT derived from the first kept candidate's commit (that would strand the true baseline and let a later `git revert` unwind only to candidate #1).

**D2 — reference evaluator location (LOCKED).** `omx-core/omx_core/reference/isaaclab/evaluator.sh`, INSIDE the package so `pip install -e` ships it and `reference_evaluator("isaaclab")` resolves it via the package anchor. exp-init (#3) later COPIES it to `.omx/profile/evaluator.sh`; #2 only provides the committed reference. `package-data` ships it for non-editable installs too (not load-bearing for the editable repo + unit-test path, which is what keeps tests Claude-free — defensive hygiene only).

**D3 — subprocess timeout/exit policy (LOCKED).** `subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True, timeout=600)`. Mapping to the EvaluationRecord (mirrors `runtime.ts:602-636`): TimeoutExpired → `status='error'`, `parse_error='timeout after Ns'` (captured, never raised); non-zero exit → `status='error'`; exit 0 + parseable last line → `status='pass'|'fail'`, carries score if numeric; exit 0 but empty/unparseable last line → `status='error'`, `parse_error` set (the pure parser RAISES `EvaluatorError`; the runner catches and records it — loud-fail parser, fault-recording runner, exactly the OMC split). `omx eval` returns rc 0 when status ∈ {pass, fail} (a graded verdict IS a successful eval), rc 1 when status='error' — so Bash callers distinguish "graded" from "broke".

**D4 — EvaluatorError home (LOCKED).** `class EvaluatorError(OmxError)` in `evaluator.py`; `OmxError(Exception)` introduced in `omx_paths.py`; `OmxPathError` reparented to `(OmxError, ValueError)`. MRO verified clean: `isinstance(e, ValueError)` still holds (all 160 baseline `pytest.raises(ValueError)` sites keep catching it), and `EvaluatorError` becomes a true sibling.

**D5 — keep_policy default (LOCKED).** OMC default = `score_improvement` (`runtime.ts:651`). `decide_outcome` takes `keep_policy` as a REQUIRED arg (no hidden default — coupling explicit at every call site) and asserts it is one of the two valid values (loud-fail symmetry with the repo's no-silent-fallback rule). `parse_keep_policy` is the surface that maps absent/empty → `score_improvement`.

---

### Task 1: omx_paths getters for #2 (OmxError base, reference paths, checkpoint pointer)

**Files:**
- Modify: `omx-core/omx_core/omx_paths.py`
- Modify: `omx-core/pyproject.toml`
- Test: `omx-core/tests/test_omx_paths.py` (append)

**Pre-flight: branch off main.**
```bash
cd /workspace/oh-my-experiments && git checkout -b feat/omx-evaluator
python3 -m pytest omx-core/tests/ -q   # expect: 160 passed (baseline)
```

- [ ] **Step 1: Write the failing tests.** Append to `omx-core/tests/test_omx_paths.py`:

```python
def test_omx_error_is_base_of_path_error():
    from omx_core.omx_paths import OmxError, OmxPathError
    assert issubclass(OmxPathError, OmxError)
    assert issubclass(OmxPathError, ValueError)  # legacy except-sites still catch it


def test_reference_dir_is_packaged(tmp_path):
    from omx_core.omx_paths import OmxPaths
    p = OmxPaths(tmp_path)
    rd = p.reference_dir
    assert rd.name == "reference"
    assert rd.parent.name == "omx_core"
    assert tmp_path not in rd.parents  # anchored to the install, never under the per-run root


def test_reference_evaluator_rejects_bad_profile(tmp_path):
    from omx_core.omx_paths import OmxPaths, OmxPathError
    import pytest
    p = OmxPaths(tmp_path)
    with pytest.raises(OmxPathError):
        p.reference_evaluator("Isaac Lab")  # space -> not a token


def test_reference_evaluator_loud_fails_when_absent(tmp_path):
    # The committed .sh ships in Task 6. Until then the getter must LOUD-FAIL
    # (not silently return a non-existent path). This is a strict assertion now,
    # and Task 6 re-asserts the resolves-success case once the file exists.
    from omx_core.omx_paths import OmxPaths, OmxPathError
    import pytest
    p = OmxPaths(tmp_path)
    ref = p.reference_dir / "isaaclab" / "evaluator.sh"
    if ref.exists():
        import pytest as _pt
        _pt.skip("reference shipped (Task 6 done); resolves-success covered there")
    with pytest.raises(OmxPathError) as ei:
        p.reference_evaluator("isaaclab")
    assert "not shipped" in str(ei.value)


def test_checkpoint_pointer_json_under_run(tmp_path):
    from omx_core.omx_paths import OmxPaths
    p = OmxPaths(tmp_path)
    cp = p.checkpoint_pointer_json("run01")
    assert cp == p.run_dir("run01") / "checkpoint-pointer.json"
```

> **TDD-rigor note (review fix):** Task 1 contains NO test that is rewritten mid-task into a both-outcomes-accepted tautology. `loud_fails_when_absent` strictly asserts the loud-fail path (genuinely true at Task-1 state) and self-skips once Task 6 ships the file. The strict *resolves-success* assertion lives in Task 6 where the file actually exists.

- [ ] **Step 2: Run to verify it fails.**

Run: `cd omx-core && python3 -m pytest tests/test_omx_paths.py -k 'omx_error or reference or checkpoint_pointer' -v`
Expected: FAIL — `ImportError: cannot import name 'OmxError'` (and AttributeErrors for the new getters).

- [ ] **Step 3: Implement in `omx-core/omx_core/omx_paths.py`.** Replace the `OmxPathError` definition:

```python
class OmxPathError(ValueError):
    """Raised on any invalid id or path-construction request (never silent)."""
```

with:

```python
class OmxError(Exception):
    """Root of every OMX loud-fail (path, evaluator, decision). Siblings live in
    other modules (e.g. evaluator.EvaluatorError) so callers can catch one base."""


class OmxPathError(OmxError, ValueError):
    """Raised on any invalid id or path-construction request (never silent).

    Multiple-inherits ValueError so pre-#2 `except ValueError` sites still catch it."""
```

Add the new getters to the `OmxPaths` class body (after `state_json`, before the permanent-tree block):

```python
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
```

- [ ] **Step 4: Add package-data to `omx-core/pyproject.toml`.** After `[tool.setuptools.packages.find]` block, add:

```toml
[tool.setuptools.package-data]
omx_core = ["reference/**/*.sh"]
```

- [ ] **Step 5: Run new + full suite.**

Run: `cd omx-core && python3 -m pytest tests/test_omx_paths.py -k 'omx_error or reference or checkpoint_pointer' -v`
Expected: PASS (5 passed — `loud_fails_when_absent` takes the strict loud-fail branch).
Run: `cd omx-core && python3 -m pytest tests/ -q`
Expected: PASS (**165 passed** — 160 baseline + 5 new). Confirms `OmxPathError` reparenting broke nothing.

- [ ] **Step 6: Commit.**

```bash
git add omx-core/omx_core/omx_paths.py omx-core/pyproject.toml omx-core/tests/test_omx_paths.py
git commit -m "feat(omx_paths): OmxError base + reference-evaluator + checkpoint-pointer getters (build-order #2)

OmxError is the shared loud-fail root so evaluator.EvaluatorError can be a sibling;
OmxPathError reparented (keeps ValueError catchers). reference_evaluator(profile)
resolves the COMMITTED reference .sh from the installed package (B4); checkpoint_
pointer_json is the B6 weights-revert pointer file. Package-data ships the .sh.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: parse_evaluator_result — loud-fail contract parser

**Files:**
- Create: `omx-core/omx_core/evaluator.py`
- Test: `omx-core/tests/test_evaluator.py`

- [ ] **Step 1: Write the failing tests.** Create `omx-core/tests/test_evaluator.py`:

```python
import json
import pytest
from omx_core.evaluator import parse_evaluator_result, EvaluatorError
from omx_core.omx_paths import OmxError


def test_pass_only_returns_pass_no_score():
    assert parse_evaluator_result('{"pass": true}') == {"pass": True}


def test_pass_with_numeric_score():
    assert parse_evaluator_result('{"pass": false, "score": 0.42}') == {"pass": False, "score": 0.42}


def test_integer_score_is_numeric():
    assert parse_evaluator_result('{"pass": true, "score": 3}') == {"pass": True, "score": 3}


def test_bad_json_raises():
    with pytest.raises(EvaluatorError):
        parse_evaluator_result("{not valid json")


def test_non_object_raises():
    with pytest.raises(EvaluatorError):
        parse_evaluator_result("[1, 2, 3]")
    with pytest.raises(EvaluatorError):
        parse_evaluator_result("true")


def test_missing_pass_raises():
    with pytest.raises(EvaluatorError):
        parse_evaluator_result('{"score": 0.5}')


def test_pass_must_be_bool_not_truthy():
    # contracts.ts requires typeof === 'boolean'; 1/"true" must NOT pass
    with pytest.raises(EvaluatorError):
        parse_evaluator_result('{"pass": 1}')
    with pytest.raises(EvaluatorError):
        parse_evaluator_result('{"pass": "true"}')


def test_non_numeric_score_raises():
    with pytest.raises(EvaluatorError):
        parse_evaluator_result('{"pass": true, "score": "high"}')


def test_bool_score_rejected():
    # JSON true is not a number; Python bool is an int subclass so guard explicitly
    with pytest.raises(EvaluatorError):
        parse_evaluator_result('{"pass": true, "score": true}')


def test_evaluator_error_is_omx_error():
    assert issubclass(EvaluatorError, OmxError)
```

- [ ] **Step 2: Run to verify it fails.**

Run: `cd omx-core && python3 -m pytest tests/test_evaluator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.evaluator'`.

- [ ] **Step 3: Write the implementation.** Create `omx-core/omx_core/evaluator.py` (parser + error class only; runner added in Task 3):

```python
"""omx_core.evaluator — re-implementation of OMC's evaluator contract (NEVER imported).

Mirrors src/autoresearch/contracts.ts parseEvaluatorResult (lines 178-201) and
runtime.ts runAutoresearchEvaluator (lines 586-636), in pure Python:
  - parse_evaluator_result: loud-fail JSON -> {pass} or {pass, score}.
  - run_evaluator (Task 3): subprocess, LAST stdout line parsed, fault-recorded.

The parser is strictly loud-fail (raises EvaluatorError); the runner is
fault-tolerant-by-RECORDING (captures the failure into the EvaluationRecord so
the decision tree turns it into 'discard', never crashing the loop).
"""
import json

from omx_core.omx_paths import OmxError


class EvaluatorError(OmxError):
    """Raised by the loud-fail parser on bad JSON / missing pass / non-numeric score."""


def _is_number(x) -> bool:
    # JSON numbers parse to int/float; reject bool (JSON true/false is not a number,
    # but Python bool is an int subclass, so exclude it explicitly).
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def parse_evaluator_result(raw: str) -> dict:
    """Parse evaluator stdout JSON. Returns {'pass': bool} or {'pass', 'score'}.

    Loud-fail (EvaluatorError) on: invalid JSON, non-object, missing/non-bool
    'pass', or 'score' present but non-numeric. Mirrors contracts.ts:178-201.
    (OMC uses a bare `catch {}` around JSON.parse; (ValueError, TypeError) is the
    faithful Python equivalent — json.loads raises JSONDecodeError<:ValueError on
    bad JSON, TypeError on non-str input.)
    """
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise EvaluatorError(
            "Evaluator output must be valid JSON with required boolean pass "
            "and optional numeric score.") from e
    if not isinstance(parsed, dict):
        raise EvaluatorError("Evaluator output must be a JSON object.")
    if not isinstance(parsed.get("pass"), bool):
        raise EvaluatorError("Evaluator output must include boolean pass.")
    if "score" in parsed and not _is_number(parsed["score"]):
        raise EvaluatorError("Evaluator output score must be numeric when provided.")
    if "score" in parsed:
        return {"pass": parsed["pass"], "score": parsed["score"]}
    return {"pass": parsed["pass"]}
```

- [ ] **Step 4: Run to verify it passes.**

Run: `cd omx-core && python3 -m pytest tests/test_evaluator.py -v`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit.**

```bash
git add omx-core/omx_core/evaluator.py omx-core/tests/test_evaluator.py
git commit -m "feat(evaluator): parse_evaluator_result — loud-fail contract parser (build-order #2)

Pure re-impl of contracts.ts:178-201: JSON.parse, require boolean pass, score
optional-but-numeric. EvaluatorError(OmxError). bool 'score'/'pass' rejected
explicitly (Python bool is an int subclass).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: run_evaluator — subprocess runner (LAST stdout line, fault-recorded)

**Files:**
- Modify: `omx-core/omx_core/evaluator.py`
- Test: `omx-core/tests/test_evaluator.py` (append)

- [ ] **Step 1: Write the failing tests.** Append to `omx-core/tests/test_evaluator.py`:

```python
from omx_core.evaluator import run_evaluator


def test_run_passes_last_line_only(tmp_path):
    # noise on earlier lines must be ignored; LAST non-empty line is the verdict
    rec = run_evaluator('printf "loading...\\nrunning eval\\n{\\"pass\\": true, \\"score\\": 0.9}\\n"', cwd=tmp_path)
    assert rec["status"] == "pass"
    assert rec["pass"] is True
    assert rec["score"] == 0.9
    assert rec["exit_code"] == 0


def test_run_fail_verdict(tmp_path):
    rec = run_evaluator('echo "{\\"pass\\": false}"', cwd=tmp_path)
    assert rec["status"] == "fail"
    assert rec["pass"] is False
    assert "score" not in rec


def test_run_trailing_blank_lines_ignored(tmp_path):
    rec = run_evaluator('printf "{\\"pass\\": true}\\n\\n\\n"', cwd=tmp_path)
    assert rec["status"] == "pass"


def test_run_nonzero_exit_is_error(tmp_path):
    rec = run_evaluator('echo "{\\"pass\\": true}"; exit 7', cwd=tmp_path)
    assert rec["status"] == "error"
    assert rec["exit_code"] == 7


def test_run_unparseable_last_line_is_error(tmp_path):
    rec = run_evaluator('echo "not json at all"', cwd=tmp_path)
    assert rec["status"] == "error"
    assert "parse_error" in rec


def test_run_empty_stdout_is_error(tmp_path):
    rec = run_evaluator('true', cwd=tmp_path)   # exit 0, no stdout
    assert rec["status"] == "error"
    assert "parse_error" in rec


def test_run_timeout_is_error_not_raise(tmp_path):
    rec = run_evaluator('sleep 5', cwd=tmp_path, timeout=1)
    assert rec["status"] == "error"
    assert "timeout" in rec["parse_error"].lower()


def test_run_record_carries_command_and_stdout(tmp_path):
    rec = run_evaluator('echo "{\\"pass\\": true}"', cwd=tmp_path)
    assert "echo" in rec["command"]
    assert "pass" in rec["stdout"]
    assert "ran_at" in rec
```

- [ ] **Step 2: Run to verify it fails.**

Run: `cd omx-core && python3 -m pytest tests/test_evaluator.py -k run_ -v`
Expected: FAIL — `ImportError: cannot import name 'run_evaluator'`.

- [ ] **Step 3: Implement.** Append to `omx-core/omx_core/evaluator.py`:

```python
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _last_nonempty_line(text: str):
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return None


def run_evaluator(command: str, cwd, *, timeout: int = 600) -> dict:
    """Run `command` (shell) in `cwd`; parse its LAST non-empty stdout line.

    Returns an EvaluationRecord dict (mirrors runtime.ts AutoresearchEvaluationRecord):
      {command, ran_at, status: pass|fail|error, [pass], [score], exit_code,
       stdout, stderr, [parse_error]}.
    Fault-tolerant by RECORDING: a non-zero exit, timeout, empty stdout, or an
    unparseable last line all yield status='error' (never raises) so the decision
    tree turns it into 'discard' (evaluator-error). The pure parser still loud-fails;
    this runner catches that and records it. Mirrors runtime.ts:586-636.
    """
    ran_at = _now_iso()
    cwd = str(Path(cwd))
    try:
        proc = subprocess.run(
            command, shell=True, cwd=cwd, capture_output=True, text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return {
            "command": command, "ran_at": ran_at, "status": "error",
            "exit_code": None,
            "stdout": (e.stdout or "") if isinstance(e.stdout, str) else "",
            "stderr": (e.stderr or "") if isinstance(e.stderr, str) else "",
            "parse_error": f"timeout after {timeout}s",
        }
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return {
            "command": command, "ran_at": ran_at, "status": "error",
            "exit_code": proc.returncode, "stdout": stdout, "stderr": stderr,
        }
    last = _last_nonempty_line(stdout)
    if last is None:
        return {
            "command": command, "ran_at": ran_at, "status": "error",
            "exit_code": proc.returncode, "stdout": stdout, "stderr": stderr,
            "parse_error": "evaluator produced no parseable stdout line",
        }
    try:
        parsed = parse_evaluator_result(last)
    except EvaluatorError as e:
        return {
            "command": command, "ran_at": ran_at, "status": "error",
            "exit_code": proc.returncode, "stdout": stdout, "stderr": stderr,
            "parse_error": str(e),
        }
    record = {
        "command": command, "ran_at": ran_at,
        "status": "pass" if parsed["pass"] else "fail",
        "pass": parsed["pass"], "exit_code": proc.returncode,
        "stdout": stdout, "stderr": stderr,
    }
    if "score" in parsed:
        record["score"] = parsed["score"]
    return record
```

- [ ] **Step 4: Run to verify it passes.**

Run: `cd omx-core && python3 -m pytest tests/test_evaluator.py -v`
Expected: PASS (**18 passed** — 10 parser + 8 runner).

- [ ] **Step 5: Commit.**

```bash
git add omx-core/omx_core/evaluator.py omx-core/tests/test_evaluator.py
git commit -m "feat(evaluator): run_evaluator subprocess runner (LAST stdout line, fault-recorded)

Mirrors runtime.ts:586-636. shell subprocess, capture stdout, parse the last
non-empty line; non-zero exit / timeout / empty / unparseable -> status=error
(recorded, never raised) so the decision tree discards as evaluator-error.
Default timeout 600s.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: decide_outcome + parse_keep_policy — keep-policy tree (B5 coupling)

**Files:**
- Create: `omx-core/omx_core/decision.py`
- Test: `omx-core/tests/test_decision.py`

- [ ] **Step 1: Write the failing tests (one per branch of the OMC tree).** Create `omx-core/tests/test_decision.py`:

```python
import pytest
from omx_core.decision import decide_outcome, parse_keep_policy
from omx_core.evaluator import EvaluatorError


# --- parse_keep_policy (contracts.ts:127-137) ---
def test_keep_policy_canonical():
    assert parse_keep_policy("pass_only") == "pass_only"
    assert parse_keep_policy("score_improvement") == "score_improvement"


def test_keep_policy_case_insensitive():
    assert parse_keep_policy("  PASS_ONLY ") == "pass_only"
    assert parse_keep_policy("Score_Improvement") == "score_improvement"


def test_keep_policy_absent_defaults_score_improvement():
    assert parse_keep_policy(None) == "score_improvement"
    assert parse_keep_policy("") == "score_improvement"


def test_keep_policy_unknown_raises():
    with pytest.raises(EvaluatorError):
        parse_keep_policy("keep_everything")


# helpers
def _eval(status, **kw):
    rec = {"command": "x", "ran_at": "t", "status": status, "exit_code": 0,
           "stdout": "", "stderr": ""}
    rec.update(kw)
    return rec


# --- decide_outcome: error / no-evaluation branch (runtime.ts:697-705) ---
def test_no_evaluation_discards_as_error():
    d = decide_outcome("pass_only", None, None)
    assert d["decision"] == "discard"
    assert "error" in d["decision_reason"].lower()
    assert d["keep"] is False


def test_evaluator_error_record_discards():
    d = decide_outcome("pass_only", None, _eval("error", parse_error="boom"))
    assert d["decision"] == "discard"
    assert d["keep"] is False


# --- !pass branch (runtime.ts:706-713) ---
def test_fail_discards_under_both_policies():
    for pol in ("pass_only", "score_improvement"):
        d = decide_outcome(pol, None, _eval("fail", **{"pass": False}))
        assert d["decision"] == "discard"


# --- pass_only + pass -> keep (runtime.ts:715-722) ---
def test_pass_only_pass_keeps():
    d = decide_outcome("pass_only", None, _eval("pass", **{"pass": True}))
    assert d["decision"] == "keep"
    assert d["keep"] is True


def test_pass_only_keeps_even_without_score():
    d = decide_outcome("pass_only", 0.5, _eval("pass", **{"pass": True}))
    assert d["decision"] == "keep"   # pass_only ignores score entirely


# --- score_improvement bootstrap: no comparable last_kept_score (runtime.ts:724-738) ---
def test_bootstrap_first_numeric_score_keeps():
    d = decide_outcome("score_improvement", None, _eval("pass", **{"pass": True, "score": 0.3}))
    assert d["decision"] == "keep"
    assert "bootstrap" in d["decision_reason"].lower()


# --- score_improvement + pass but NO score -> ambiguous (B5; runtime.ts:739-745) ---
def test_score_improvement_no_score_is_ambiguous():
    d = decide_outcome("score_improvement", None, _eval("pass", **{"pass": True}))
    assert d["decision"] == "ambiguous"
    assert d["keep"] is False


def test_score_improvement_no_score_ambiguous_even_with_prior_baseline():
    # last_kept_score numeric but candidate has no score -> not comparable -> ambiguous
    # (the subtle OMC branch most re-impls get wrong: runtime.ts:724-745)
    d = decide_outcome("score_improvement", 0.5, _eval("pass", **{"pass": True}))
    assert d["decision"] == "ambiguous"


# --- score_improvement comparable: improvement vs not (runtime.ts:747-762) ---
def test_score_improves_keeps():
    d = decide_outcome("score_improvement", 0.5, _eval("pass", **{"pass": True, "score": 0.7}))
    assert d["decision"] == "keep"


def test_score_not_better_discards():
    d = decide_outcome("score_improvement", 0.5, _eval("pass", **{"pass": True, "score": 0.5}))
    assert d["decision"] == "discard"   # strictly greater required; equal discards
    d2 = decide_outcome("score_improvement", 0.5, _eval("pass", **{"pass": True, "score": 0.4}))
    assert d2["decision"] == "discard"


def test_decision_always_carries_evaluator_and_notes():
    d = decide_outcome("score_improvement", 0.5, _eval("pass", **{"pass": True, "score": 0.7}))
    assert d["evaluator"] is not None
    assert isinstance(d["notes"], list) and d["notes"]


def test_decide_outcome_rejects_unnormalized_policy():
    # decide_outcome takes a REQUIRED keep_policy and loud-fails on an invalid one
    # (no silent fall-through to score_improvement). Symmetry with the repo's
    # no-silent-fallback rule; callers pre-normalize via parse_keep_policy.
    with pytest.raises(EvaluatorError):
        decide_outcome("Pass_Only", None, _eval("pass", **{"pass": True}))
```

- [ ] **Step 2: Run to verify it fails.**

Run: `cd omx-core && python3 -m pytest tests/test_decision.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.decision'`.

- [ ] **Step 3: Implement.** Create `omx-core/omx_core/decision.py`:

```python
"""omx_core.decision — re-impl of OMC's keep-policy decision tree (NEVER imported).

Mirrors runtime.ts decideAutoresearchOutcome (lines 665-763) + comparableScore
(661-663) + contracts.ts parseKeepPolicy (127-137), pure Python. No git, no I/O —
a deterministic function from (keep_policy, last_kept_score, evaluation) to a
decision dict. The candidate-status cases (abort/noop/interrupted, runtime.ts:670-695)
belong to exp-loop (#6, which owns the candidate artifact); #2 covers the
evaluation-driven tail of the tree, which is the Claude-free unit-testable part
(design H3).

B5 coupling: under pass_only, score is irrelevant (pass -> keep). Under
score_improvement, a score-less pass is 'ambiguous' (discard) — the loud,
documented coupling contracts.ts leaves implicit.
"""
from omx_core.evaluator import EvaluatorError

_VALID = ("pass_only", "score_improvement")


def parse_keep_policy(raw) -> str:
    """Normalize keep_policy. Absent/empty -> 'score_improvement' (OMC default,
    runtime.ts:651). Unknown string -> loud-fail. Mirrors contracts.ts:127-137."""
    if raw is None:
        return "score_improvement"
    if not isinstance(raw, str):
        raise EvaluatorError("keep_policy must be a string when provided.")
    norm = raw.strip().lower()
    if not norm:
        return "score_improvement"
    if norm in _VALID:
        return norm
    raise EvaluatorError(
        f"keep_policy must be one of {list(_VALID)}, got {raw!r}.")


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _comparable_score(prev, nxt) -> bool:
    """True only when BOTH are numbers (runtime.ts:661-663)."""
    return _is_number(prev) and _is_number(nxt)


def _d(decision, reason, keep, evaluation, note):
    return {"decision": decision, "decision_reason": reason, "keep": keep,
            "evaluator": evaluation, "notes": [note]}


def decide_outcome(keep_policy: str, last_kept_score, evaluation) -> dict:
    """Decide keep/discard/ambiguous from an evaluation record. Pure.

    `keep_policy` is REQUIRED and must already be normalized (one of _VALID) —
    loud-fail otherwise (no silent fall-through). `evaluation` is the dict from
    run_evaluator (or None). Cases, in OMC order:
      no evaluation or status=='error' -> discard (evaluator error)
      pass is falsey                   -> discard
      pass_only & pass                 -> keep
      score_improvement, no comparable last_kept_score:
          candidate score numeric      -> keep   [bootstrap: becomes baseline]
          else                         -> ambiguous (discard; needs numeric score)
      score > last_kept_score          -> keep
      else                             -> discard (no improvement)
    """
    if keep_policy not in _VALID:
        raise EvaluatorError(
            f"decide_outcome keep_policy must be normalized to one of {list(_VALID)}, "
            f"got {keep_policy!r} (call parse_keep_policy first).")
    if evaluation is None or evaluation.get("status") == "error":
        return _d("discard", "evaluator error", False, evaluation,
                  "candidate discarded because evaluator errored or crashed")
    if not evaluation.get("pass"):
        return _d("discard", "evaluator reported failure", False, evaluation,
                  "candidate discarded because evaluator pass=false")
    if keep_policy == "pass_only":
        return _d("keep", "pass_only keep policy accepted evaluator pass=true",
                  True, evaluation,
                  "candidate kept because policy is pass_only")
    score = evaluation.get("score")
    if not _comparable_score(last_kept_score, score):
        if _is_number(score):
            return _d("keep", "[bootstrap] first comparable score in score_improvement run",
                      True, evaluation,
                      "candidate kept; no prior comparable score -> new baseline")
        return _d("ambiguous", "evaluator pass without numeric score", False, evaluation,
                  "candidate discarded; score_improvement requires a numeric score")
    if score > last_kept_score:
        return _d("keep", "score improved over last kept score", True, evaluation,
                  "candidate kept because evaluator score increased")
    return _d("discard", "score did not improve", False, evaluation,
              "candidate discarded because score was not better than the baseline")
```

- [ ] **Step 4: Run to verify it passes.**

Run: `cd omx-core && python3 -m pytest tests/test_decision.py -v`
Expected: PASS (**15 passed**).

- [ ] **Step 5: Commit.**

```bash
git add omx-core/omx_core/decision.py omx-core/tests/test_decision.py
git commit -m "feat(decision): decide_outcome + parse_keep_policy — keep-policy tree (B5)

Pure re-impl of runtime.ts decideAutoresearchOutcome (665-763) + comparableScore.
Exhaustive per-branch tests. B5 coupling encoded: pass_only ignores score; score_
improvement bootstraps on first numeric score, else 'ambiguous' (discard). strict
'>' for improvement. decide_outcome loud-fails on an un-normalized keep_policy
(no silent fall-through). candidate-status cases (abort/noop/interrupted) deferred to #6.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: ledger.py — trio writers + B6 hybrid-revert pointer (seed + invariance)

**Files:**
- Create: `omx-core/omx_core/ledger.py`
- Test: `omx-core/tests/test_ledger.py`

- [ ] **Step 1: Write the failing tests.** Create `omx-core/tests/test_ledger.py`:

```python
import json
import pytest
from omx_core.omx_paths import OmxPaths
from omx_core.ledger import (
    append_results_row, append_ledger_entry, append_decision_log,
    seed_ledger, record_iteration, RESULTS_HEADER,
)


def test_results_tsv_header_written_once(tmp_path):
    p = OmxPaths(tmp_path)
    append_results_row(p, "run01", {"iteration": 0, "commit": "abc1234", "pass": True,
                                    "score": 0.5, "status": "keep", "description": "first"})
    append_results_row(p, "run01", {"iteration": 1, "commit": "def5678", "pass": False,
                                    "score": None, "status": "discard", "description": "second"})
    text = p.results_tsv("run01").read_text()
    assert text.startswith(RESULTS_HEADER)
    assert text.count(RESULTS_HEADER) == 1   # header not duplicated
    rows = text.strip().splitlines()
    assert len(rows) == 3                     # header + 2
    assert "\t" in rows[1]
    assert rows[2].split("\t")[3] == ""       # None score -> blank cell


def test_ledger_json_accumulates_entries(tmp_path):
    p = OmxPaths(tmp_path)
    append_ledger_entry(p, "run01", {"iteration": 0, "decision": "keep",
                                     "decision_reason": "x", "candidate_checkpoint": "m0.pt"})
    append_ledger_entry(p, "run01", {"iteration": 1, "decision": "discard",
                                     "decision_reason": "y", "candidate_checkpoint": "m1.pt"})
    data = json.loads(p.ledger_json("run01").read_text())
    assert data["schema_version"] == 1
    assert len(data["entries"]) == 2
    assert data["entries"][1]["decision"] == "discard"


def test_decision_log_prose_blocks(tmp_path):
    p = OmxPaths(tmp_path)
    append_decision_log(p, "run01", {"iteration": 0, "decision": "keep",
        "description": "tune kd", "reason": "score up",
        "evaluator": {"status": "pass", "pass": True, "score": 0.7}, "notes": ["n1"]})
    text = p.decision_log("run01").read_text()
    assert text.startswith("# OMX Decision Log")
    assert "## Iteration 0 — keep" in text
    assert "- Score: 0.7" in text
    assert "  - n1" in text


# --- B6: baseline_commit is SEEDED at run-init and INVARIANT across keeps/discards ---
def test_seed_ledger_sets_invariant_baseline(tmp_path):
    p = OmxPaths(tmp_path)
    seed_ledger(p, "run01", baseline_commit="base000", keep_policy="score_improvement")
    led = json.loads(p.ledger_json("run01").read_text())
    assert led["baseline_commit"] == "base000"
    assert led["keep_policy"] == "score_improvement"
    assert led["last_kept_commit"] is None         # not advanced yet
    assert led["last_kept_checkpoint"] is None


def test_baseline_commit_invariant_across_keep_and_discard(tmp_path):
    p = OmxPaths(tmp_path)
    seed_ledger(p, "run01", baseline_commit="base000", keep_policy="score_improvement")
    keep = {"decision": "keep", "decision_reason": "r", "keep": True,
            "evaluator": {"status": "pass", "pass": True, "score": 0.7}, "notes": ["n"]}
    record_iteration(p, "run01", iteration=0, decision=keep,
                     candidate_checkpoint="/w/m0.pt", candidate_commit="cand111", description="x")
    disc = {"decision": "discard", "decision_reason": "r", "keep": False,
            "evaluator": {"status": "pass", "pass": True, "score": 0.4}, "notes": ["n"]}
    record_iteration(p, "run01", iteration=1, decision=disc,
                     candidate_checkpoint="/w/m1.pt", candidate_commit="cand222", description="y")
    led = json.loads(p.ledger_json("run01").read_text())
    # baseline_commit is the PRE-experiment anchor — never the first kept candidate's commit
    assert led["baseline_commit"] == "base000"
    assert led["last_kept_commit"] == "cand111"   # config pointer advanced on keep only


# --- B6: keep ADVANCES the checkpoint pointer (ledger + mirror) ---
def test_record_iteration_keep_advances_checkpoint_and_commit(tmp_path):
    p = OmxPaths(tmp_path)
    seed_ledger(p, "run01", baseline_commit="base000", keep_policy="score_improvement")
    decision = {"decision": "keep", "decision_reason": "score up", "keep": True,
                "evaluator": {"status": "pass", "pass": True, "score": 0.7}, "notes": ["n"]}
    record_iteration(p, "run01", iteration=0, decision=decision,
                     candidate_checkpoint="/w/model_100.pt", candidate_commit="abc1234",
                     description="tune")
    led = json.loads(p.ledger_json("run01").read_text())
    assert led["last_kept_checkpoint"] == "/w/model_100.pt"   # advanced
    assert led["last_kept_commit"] == "abc1234"               # config side advanced
    assert led["last_kept_score"] == 0.7
    ptr = json.loads(p.checkpoint_pointer_json("run01").read_text())
    assert ptr["last_kept_checkpoint"] == "/w/model_100.pt"   # mirror written


# --- B6: discard LEAVES the pointer (no advance, NO git/rm on weights) ---
def test_record_iteration_discard_leaves_checkpoint(tmp_path):
    p = OmxPaths(tmp_path)
    seed_ledger(p, "run01", baseline_commit="base000", keep_policy="score_improvement")
    keep = {"decision": "keep", "decision_reason": "r", "keep": True,
            "evaluator": {"status": "pass", "pass": True, "score": 0.7}, "notes": ["n"]}
    record_iteration(p, "run01", iteration=0, decision=keep,
                     candidate_checkpoint="/w/model_100.pt", candidate_commit="aaa1111",
                     description="keep it")
    disc = {"decision": "discard", "decision_reason": "no improvement", "keep": False,
            "evaluator": {"status": "pass", "pass": True, "score": 0.4}, "notes": ["n"]}
    discarded = tmp_path / "model_200.pt"
    discarded.write_text("weights")
    record_iteration(p, "run01", iteration=1, decision=disc,
                     candidate_checkpoint=str(discarded), candidate_commit="bbb2222",
                     description="reject it")
    led = json.loads(p.ledger_json("run01").read_text())
    assert led["last_kept_checkpoint"] == "/w/model_100.pt"   # LEFT at the kept one
    assert led["last_kept_commit"] == "aaa1111"               # config pointer unchanged
    assert led["last_kept_score"] == 0.7                       # baseline unchanged
    assert discarded.exists()                                  # NO rm on weights
    assert discarded.read_text() == "weights"                  # NO git op / mutation
    ptr = json.loads(p.checkpoint_pointer_json("run01").read_text())
    assert ptr["last_kept_checkpoint"] == "/w/model_100.pt"


# --- B6: a NON-keep status beyond 'discard' (ambiguous) also LEAVES the pointer ---
def test_record_iteration_ambiguous_leaves_checkpoint(tmp_path):
    p = OmxPaths(tmp_path)
    seed_ledger(p, "run01", baseline_commit="base000", keep_policy="score_improvement")
    keep = {"decision": "keep", "decision_reason": "r", "keep": True,
            "evaluator": {"status": "pass", "pass": True, "score": 0.7}, "notes": ["n"]}
    record_iteration(p, "run01", iteration=0, decision=keep,
                     candidate_checkpoint="/w/model_100.pt", candidate_commit="aaa1111",
                     description="keep it")
    amb = {"decision": "ambiguous", "decision_reason": "pass without numeric score",
           "keep": False, "evaluator": {"status": "pass", "pass": True}, "notes": ["n"]}
    record_iteration(p, "run01", iteration=1, decision=amb,
                     candidate_checkpoint="/w/model_200.pt", candidate_commit="bbb2222",
                     description="ambiguous one")
    led = json.loads(p.ledger_json("run01").read_text())
    assert led["last_kept_checkpoint"] == "/w/model_100.pt"   # pointer LEFT for ambiguous too
    assert led["last_kept_commit"] == "aaa1111"


def test_record_iteration_writes_all_three_artifacts(tmp_path):
    p = OmxPaths(tmp_path)
    seed_ledger(p, "run01", baseline_commit="base000", keep_policy="pass_only")
    d = {"decision": "keep", "decision_reason": "r", "keep": True,
         "evaluator": {"status": "pass", "pass": True, "score": 0.7}, "notes": ["n"]}
    record_iteration(p, "run01", iteration=0, decision=d,
                     candidate_checkpoint="/w/m.pt", candidate_commit="c", description="x")
    assert p.results_tsv("run01").exists()
    assert p.ledger_json("run01").exists()
    assert p.decision_log("run01").exists()
    # atomic: no .tmp leftovers in the run dir
    leftovers = [f.name for f in p.run_dir("run01").iterdir() if f.name.endswith(".tmp")]
    assert leftovers == []
```

- [ ] **Step 2: Run to verify it fails.**

Run: `cd omx-core && python3 -m pytest tests/test_ledger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.ledger'`.

- [ ] **Step 3: Implement.** Create `omx-core/omx_core/ledger.py`:

```python
"""omx_core.ledger — the autoresearch 3-artifact trio + B6 hybrid-revert pointer.

Writes results.tsv (terse rows) + ledger.json (structured ledger) + decision-log.md
(prose), all through omx_paths getters with atomic writes. Mirrors runtime.ts
appendAutoresearchResultsRow / appendAutoresearchLedgerEntry / appendDecisionLog,
terse Python.

B6 hybrid revert (LOCKED schema, design §0.1 / §9 carry):
  - CONFIG edits revert via git -> ledger records baseline_commit (the PRE-experiment
    anchor, SEEDED at run-init by seed_ledger and INVARIANT) + last_kept_commit
    (advances on keep). #2 only RECORDS these; exp-loop (#6) runs the actual git revert.
  - TRAINED WEIGHTS revert via a POINTER, never a git/rm op: last_kept_checkpoint.
    keep advances it to the candidate's checkpoint; any non-keep (discard/ambiguous/
    noop/abort/interrupted/error) LEAVES it. #2 performs ZERO filesystem mutation on
    any weight file — physical checkpoint GC is #6's job (deferred per §9, out of scope
    here). A mirror checkpoint-pointer.json lets #6 read the pointer without parsing
    the whole ledger; ledger and mirror are two sequential atomic writes, LEDGER
    AUTHORITATIVE (mirror may transiently lag on crash).
"""
import json

from omx_core.omx_paths import OmxPaths, atomic_path

# byte-identical to runtime.ts AUTORESEARCH_RESULTS_HEADER (line 146)
RESULTS_HEADER = "iteration\tcommit\tpass\tscore\tstatus\tdescription\n"


def _pass_cell(v):
    return "" if v is None else ("true" if v else "false")


def _score_cell(v):
    # repr(float) matches JS String(value) for the score range we use (0.5, 0.7, 3,
    # None->''); they can diverge on extreme exponents (e.g. 1e-05), which no contract
    # path depends on (scores round-trip through JSON, not this readability cell).
    return "" if v is None else repr(v) if isinstance(v, float) else str(v)


def _default_ledger() -> dict:
    return {"schema_version": 1, "keep_policy": None,
            "baseline_commit": None, "last_kept_commit": None,
            "last_kept_score": None, "last_kept_checkpoint": None, "entries": []}


def _load_ledger(target) -> dict:
    if target.exists():
        return json.loads(target.read_text())
    return _default_ledger()


def append_results_row(paths: OmxPaths, run_id, row: dict) -> None:
    """Append one terse TSV row; write the header first if the file is new."""
    target = paths.results_tsv(run_id)
    existing = target.read_text() if target.exists() else RESULTS_HEADER
    line = "\t".join([
        str(row["iteration"]), str(row["commit"]),
        _pass_cell(row.get("pass")), _score_cell(row.get("score")),
        str(row["status"]), str(row["description"]),
    ]) + "\n"
    with atomic_path(target) as tmp:
        tmp.write_text(existing + line)


def append_ledger_entry(paths: OmxPaths, run_id, entry: dict) -> None:
    """Append one structured entry to ledger.json (accumulating, atomic)."""
    target = paths.ledger_json(run_id)
    led = _load_ledger(target)
    led["entries"].append(entry)
    with atomic_path(target) as tmp:
        tmp.write_text(json.dumps(led, indent=2, sort_keys=True))


def append_decision_log(paths: OmxPaths, run_id, entry: dict) -> None:
    """Append one prose decision block to decision-log.md (mirrors appendDecisionLog)."""
    target = paths.decision_log(run_id)
    lines = [f"## Iteration {entry['iteration']} — {entry['decision']}", "",
             f"- Description: {entry['description']}", f"- Reason: {entry['reason']}"]
    ev = entry.get("evaluator")
    if ev:
        score = ev.get("score")
        lines += [f"- Evaluator status: {ev.get('status')}",
                  f"- Pass: {ev.get('pass', '')}",
                  f"- Score: {score if isinstance(score, (int, float)) else ''}"]
    notes = entry.get("notes") or []
    if notes:
        lines.append("- Notes:")
        lines += [f"  - {n}" for n in notes]
    lines += ["", ""]
    existing = target.read_text() if target.exists() else "# OMX Decision Log\n\n"
    with atomic_path(target) as tmp:
        tmp.write_text(existing + "\n".join(lines))


def seed_ledger(paths: OmxPaths, run_id, *, baseline_commit, keep_policy) -> None:
    """Initialize ledger.json with the PRE-experiment anchor (B6).

    baseline_commit is the config git-revert target — the point a revert unwinds TO.
    It is set ONCE here at run-init and held INVARIANT; record_iteration never
    derives it from a kept candidate. Idempotent-ish: re-seeding overwrites the
    anchor fields but is intended to be called exactly once before iteration 0.
    """
    target = paths.ledger_json(run_id)
    led = _load_ledger(target)
    led["baseline_commit"] = baseline_commit
    led["keep_policy"] = keep_policy
    with atomic_path(target) as tmp:
        tmp.write_text(json.dumps(led, indent=2, sort_keys=True))


def record_iteration(paths: OmxPaths, run_id, *, iteration, decision,
                     candidate_checkpoint, candidate_commit, description) -> None:
    """Write all three artifacts for one iteration AND apply the B6 pointer rule.

    `decision` is the dict from decide_outcome. On keep -> advance last_kept_commit
    /last_kept_checkpoint (and last_kept_score when numeric) to this candidate;
    otherwise LEAVE them. baseline_commit is NEVER touched here (seeded by
    seed_ledger). Performs NO filesystem op on any weight file (only the pointer
    string moves).
    """
    ev = decision.get("evaluator") or {}
    score = ev.get("score")
    status = decision["decision"]
    keep = decision.get("keep", False)

    # 1) results.tsv
    append_results_row(paths, run_id, {
        "iteration": iteration, "commit": candidate_commit,
        "pass": ev.get("pass"), "score": score, "status": status,
        "description": description,
    })
    # 2) ledger.json (entry + B6 pointer advance/leave in the same atomic write)
    target = paths.ledger_json(run_id)
    led = _load_ledger(target)
    led["entries"].append({
        "iteration": iteration, "decision": status,
        "decision_reason": decision["decision_reason"],
        "candidate_checkpoint": candidate_checkpoint,
        "candidate_commit": candidate_commit,
        "evaluator": ev or None, "notes": decision.get("notes", []),
        "description": description,
    })
    if keep:
        led["last_kept_checkpoint"] = candidate_checkpoint   # ADVANCE (pointer only)
        led["last_kept_commit"] = candidate_commit
        # leave-prior on a score-less keep (pass_only): only advance when numeric.
        # matches the per-iteration OMC path (runtime.ts:1466); #6 must not "fix" to null.
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            led["last_kept_score"] = score
    # non-keep (discard/ambiguous/...): pointer LEFT untouched; NO git/rm on weights.
    with atomic_path(target) as tmp:
        tmp.write_text(json.dumps(led, indent=2, sort_keys=True))
    # 3) checkpoint-pointer.json mirror (derived; ledger is authoritative)
    ptr_target = paths.checkpoint_pointer_json(run_id)
    with atomic_path(ptr_target) as tmp:
        tmp.write_text(json.dumps(
            {"last_kept_checkpoint": led["last_kept_checkpoint"]},
            indent=2, sort_keys=True))
    # 4) decision-log.md
    append_decision_log(paths, run_id, {
        "iteration": iteration, "decision": status, "description": description,
        "reason": decision["decision_reason"], "evaluator": ev or None,
        "notes": decision.get("notes", []),
    })
```

- [ ] **Step 4: Run to verify it passes.**

Run: `cd omx-core && python3 -m pytest tests/test_ledger.py -v`
Expected: PASS (**9 passed**).

- [ ] **Step 5: Commit.**

```bash
git add omx-core/omx_core/ledger.py omx-core/tests/test_ledger.py
git commit -m "feat(ledger): autoresearch trio writers + B6 hybrid-revert pointer (code+tests)

results.tsv/ledger.json/decision-log.md via omx_paths, atomic. seed_ledger sets the
PRE-experiment baseline_commit anchor (INVARIANT, never derived from a kept candidate).
record_iteration encodes B6: keep advances last_kept_checkpoint+commit+score, any
non-keep (discard/ambiguous/...) LEAVES them, and performs ZERO filesystem op on
weight files (only the pointer string moves); physical checkpoint GC deferred to #6.
Mirror checkpoint-pointer.json written (ledger authoritative).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: committed Isaac Lab REFERENCE evaluator.sh (ships pass_only)

**Files:**
- Create: `omx-core/omx_core/reference/__init__.py`
- Create: `omx-core/omx_core/reference/isaaclab/evaluator.sh`
- Test: `omx-core/tests/test_reference_evaluator.py`

- [ ] **Step 1: Write the failing tests.** Create `omx-core/tests/test_reference_evaluator.py`:

```python
import os
from omx_core.omx_paths import OmxPaths
from omx_core.evaluator import run_evaluator, parse_evaluator_result
from omx_core.decision import decide_outcome


def test_reference_evaluator_resolves_committed_file(tmp_path):
    # the strict resolves-success assertion deferred from Task 1 — the file ships here
    p = OmxPaths(tmp_path)
    ev = p.reference_evaluator("isaaclab")
    assert ev.name == "evaluator.sh"
    assert ev.parent.name == "isaaclab"
    assert ev.exists()


def test_reference_evaluator_file_is_executable(tmp_path):
    p = OmxPaths(tmp_path)
    ev = p.reference_evaluator("isaaclab")
    assert os.access(ev, os.X_OK)   # committed executable bit


def test_reference_evaluator_emits_contract_json(tmp_path):
    p = OmxPaths(tmp_path)
    ev = p.reference_evaluator("isaaclab")
    rec = run_evaluator(f"bash {ev}", cwd=tmp_path)
    # stub ships pass_only: a parseable {pass: bool} verdict, status pass/fail
    assert rec["status"] in ("pass", "fail")
    assert isinstance(rec["pass"], bool)


def test_reference_last_line_parses_through_contract(tmp_path):
    p = OmxPaths(tmp_path)
    ev = p.reference_evaluator("isaaclab")
    rec = run_evaluator(f"bash {ev}", cwd=tmp_path)
    parsed = parse_evaluator_result(rec["stdout"].splitlines()[-1])
    assert "pass" in parsed


def test_reference_with_pass_only_policy_decides(tmp_path):
    # end-to-end: reference (pass_only) -> decide_outcome keeps on pass
    p = OmxPaths(tmp_path)
    ev = p.reference_evaluator("isaaclab")
    rec = run_evaluator(f"OMX_REF_PASS=1 bash {ev}", cwd=tmp_path)
    d = decide_outcome("pass_only", None, rec)
    assert d["decision"] == "keep"
```

- [ ] **Step 2: Run to verify it fails.**

Run: `cd omx-core && python3 -m pytest tests/test_reference_evaluator.py -v`
Expected: FAIL — `reference evaluator not shipped for 'isaaclab'` (OmxPathError) / file absent.

- [ ] **Step 3: Create the reference package marker.** Create `omx-core/omx_core/reference/__init__.py`:

```python
"""omx_core.reference — committed reference profiles shipped with omx-core.

Holds the COMMITTED reference evaluators (e.g. isaaclab/evaluator.sh) that
exp-init (#3) copies into a user's .omx/profile/. NOT user-elicited (B4): these
are the shipped contract demonstrations, version-controlled with the package.
"""
```

- [ ] **Step 4: Create the reference evaluator.** Create `omx-core/omx_core/reference/isaaclab/evaluator.sh`:

```bash
#!/usr/bin/env bash
# OMX Isaac Lab REFERENCE evaluator (committed; ships keep_policy=pass_only).
#
# CONTRACT (re-impl of OMC contracts.ts:178-201): the LAST non-empty stdout line
# MUST be a JSON object {"pass": <bool>} with an OPTIONAL numeric "score". Under
# pass_only (this reference's default) score is omitted; exp-init (#3) fills the
# D5 score formula later when a profile opts into score_improvement.
#
# This is an HONEST DOCUMENTED STUB. A live run is NOT invoked here (eval_dr needs
# Isaac Sim + a checkpoint, unavailable in unit tests). The block below shows
# EXACTLY where the live eval slots in; the stub emits a deterministic verdict so
# the contract is testable end-to-end without a GPU.
#
# To make this a REAL evaluator, exp-init replaces the STUB block with, e.g.:
#   cd /workspace/constrained-albc && python constrained_albc/analysis/eval_dr.py static \
#       --task "$OMX_TASK" --num_envs 64 --headless >/dev/null 2>&1
#   # then parse the run's summary.json into a pass/score verdict and echo it.
set -euo pipefail

# --- STUB verdict (replace with live eval_dr in exp-init) -------------------
# Honors OMX_REF_PASS for deterministic tests: 1/unset -> pass, 0 -> fail.
if [[ "${OMX_REF_PASS:-1}" == "0" ]]; then
  echo '{"pass": false}'
else
  echo '{"pass": true}'
fi
```

- [ ] **Step 5: Make it executable + verify git records the bit.**

```bash
chmod +x omx-core/omx_core/reference/isaaclab/evaluator.sh
git add omx-core/omx_core/reference/isaaclab/evaluator.sh
git ls-files -s omx-core/omx_core/reference/isaaclab/evaluator.sh   # expect leading 100755
```

Expected: leading `100755` (executable bit committed).

- [ ] **Step 6: Run new + the previously-deferred Task-1 path + full reference path.**

Run: `cd omx-core && python3 -m pytest tests/test_reference_evaluator.py -v`
Expected: PASS (5 passed).
Run: `cd omx-core && python3 -m pytest tests/test_omx_paths.py -k reference -v`
Expected: PASS — `test_reference_evaluator_loud_fails_when_absent` now self-skips (file ships), `rejects_bad_profile` still passes.

- [ ] **Step 7: Commit.**

```bash
git add omx-core/omx_core/reference/__init__.py omx-core/omx_core/reference/isaaclab/evaluator.sh omx-core/tests/test_reference_evaluator.py
git commit -m "feat(reference): committed Isaac Lab reference evaluator.sh (ships pass_only, B4/B5)

Honest documented stub: emits a contract-valid {pass} JSON last line (pass_only)
so the evaluator contract is testable end-to-end with no GPU; the block shows
exactly where live eval_dr slots in (exp-init, #3, swaps it). Executable bit
committed (100755). Strict resolves-success test lives here (deferred from Task 1).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: CLI verb `omx eval` (Claude-free, Bash-unit-testable) + B5 coupling end-to-end

**Files:**
- Modify: `omx-core/omx_core/cli.py`
- Test: `omx-core/tests/test_cli.py` (append)

- [ ] **Step 1: Write the failing tests.** Append to `omx-core/tests/test_cli.py`:

```python
def test_eval_reference_prints_contract_json(capsys):
    rc = main(["eval", "--command", "echo '{\"pass\": true, \"score\": 0.8}'"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pass"
    assert out["pass"] is True
    assert out["score"] == 0.8


def test_eval_fail_verdict_is_rc0(capsys):
    # a graded FAIL is a successful eval (the evaluator worked) -> rc 0
    rc = main(["eval", "--command", "echo '{\"pass\": false}'"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "fail"


def test_eval_evaluator_error_is_rc1(capsys):
    # evaluator itself broke (unparseable) -> rc 1 so Bash can distinguish
    rc = main(["eval", "--command", "echo not-json"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "error"
    assert "parse_error" in out


def test_eval_nonzero_exit_is_rc1(capsys):
    rc = main(["eval", "--command", "exit 3"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "error"


def test_eval_with_decision_pass_only_keeps(capsys):
    rc = main(["eval", "--command", "echo '{\"pass\": true}'", "--keep-policy", "pass_only"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"]["decision"] == "keep"


def test_eval_b5_scoreless_under_score_improvement_is_ambiguous(capsys):
    # B5 coupling end-to-end: score-less pass under score_improvement -> ambiguous
    rc = main(["eval", "--command", "echo '{\"pass\": true}'", "--keep-policy", "score_improvement"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"]["decision"] == "ambiguous"


def test_eval_b5_scoreless_under_pass_only_keeps(capsys):
    # ...the SAME score-less candidate keeps under pass_only (the coupling's other half)
    rc = main(["eval", "--command", "echo '{\"pass\": true}'", "--keep-policy", "pass_only"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"]["decision"] == "keep"


def test_eval_score_improvement_with_score_keeps(capsys):
    rc = main(["eval", "--command", "echo '{\"pass\": true, \"score\": 0.9}'",
               "--keep-policy", "score_improvement", "--last-kept-score", "0.5"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"]["decision"] == "keep"


def test_eval_unknown_keep_policy_errors(capsys):
    rc = main(["eval", "--command", "echo '{\"pass\": true}'", "--keep-policy", "bogus"])
    assert rc != 0
```

- [ ] **Step 2: Run to verify it fails.**

Run: `cd omx-core && python3 -m pytest tests/test_cli.py -k eval -v`
Expected: FAIL — `argument cmd: invalid choice: 'eval'`.

- [ ] **Step 3: Implement.** In `omx-core/omx_core/cli.py`, add imports (after the existing imports):

```python
from omx_core.evaluator import run_evaluator
from omx_core.decision import decide_outcome, parse_keep_policy
from omx_core.omx_paths import OmxError
```

Add the command handler (after `_cmd_session_id`):

```python
def _cmd_eval(args) -> int:
    """Run an evaluator command, print its contract record (+ optional decision).

    rc 0 when the evaluator produced a graded verdict (status pass|fail);
    rc 1 when the evaluator itself errored (status error) — so Bash callers can
    tell 'graded' from 'broke'. With --keep-policy, also runs decide_outcome and
    embeds a 'decision' block (B5 coupling visible from the CLI).
    """
    rec = run_evaluator(args.command, cwd=args.cwd or os.getcwd(), timeout=args.timeout)
    out = dict(rec)
    if args.keep_policy is not None:
        try:
            policy = parse_keep_policy(args.keep_policy)
        except OmxError as e:
            raise SystemExit(str(e))
        out["decision"] = decide_outcome(policy, args.last_kept_score, rec)
    print(json.dumps(out))
    return 0 if rec["status"] in ("pass", "fail") else 1
```

In `build_parser()`, register the verb (before `return p`):

```python
    pe = sub.add_parser("eval", help="run an evaluator command, parse {pass,score?} (Claude-free)")
    pe.add_argument("--command", required=True, help="shell command; LAST stdout line must be the JSON verdict")
    pe.add_argument("--cwd", default=None, help="working dir for the command (default: cwd)")
    pe.add_argument("--timeout", type=int, default=600, help="seconds before the evaluator is killed (status=error)")
    pe.add_argument("--keep-policy", default=None, dest="keep_policy",
                    help="pass_only | score_improvement; when set, embeds a decide_outcome block")
    pe.add_argument("--last-kept-score", type=float, default=None, dest="last_kept_score",
                    help="prior baseline score for score_improvement comparison")
    pe.set_defaults(func=_cmd_eval)
```

- [ ] **Step 4: Run new + full suite.**

Run: `cd omx-core && python3 -m pytest tests/test_cli.py -k eval -v`
Expected: PASS (9 passed).
Run: `cd omx-core && python3 -m pytest tests/ -q`
Expected: PASS (**221 passed**, zero failures) — 160 baseline + Task1(5) + Task2(10) + Task3(8) + Task4(15) + Task5(9) + Task6(5) + Task7(9). If the printed total differs, a test was added/dropped vs plan — investigate before proceeding.

- [ ] **Step 5: Smoke-test the CLI from Bash (Claude-free proof).**

```bash
cd /workspace/oh-my-experiments/omx-core && python3 -m omx_core.cli eval \
  --command "echo '{\"pass\": true, \"score\": 0.7}'" \
  --keep-policy score_improvement --last-kept-score 0.5
echo "rc=$?"
```

Expected: one JSON line with `"status": "pass"` and `"decision": {... "decision": "keep" ...}`; `rc=0`.

> **Shell-escaping note (review fix):** the evaluator command uses single-quoted JSON (`'{"pass": ...}'`) inside a double-quoted `--command` value — the proven form from the Task-7 unit tests. Do NOT write `--command 'echo {\"pass\":true}'`: bash brace-expands `{...,...}` on the comma and `echo` collapses the backslash-quotes, producing invalid JSON → `status=error`, `rc=1`.

- [ ] **Step 6: Commit.**

```bash
git add omx-core/omx_core/cli.py omx-core/tests/test_cli.py
git commit -m "feat(cli): omx eval — Claude-free evaluator runner + B5 decision coupling

Runs an evaluator command, prints the {pass,score?} contract record; rc 0 on a
graded verdict, rc 1 when the evaluator itself errored. Optional --keep-policy
/--last-kept-score embeds decide_outcome so the B5 coupling (score-less pass:
ambiguous under score_improvement, keep under pass_only) is visible from Bash.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7 (branch close): full suite once more.**

```bash
cd /workspace/oh-my-experiments && python3 -m pytest omx-core/tests/ -q
```

Expected: all green, **221 passed**, zero failures. Build-order #2 deliverables complete on `feat/omx-evaluator` (evaluator runner, decision tree, B6 ledger+pointer, trio writers, reference evaluator, `omx eval`, B5 coupling). Leave the branch for the two-stage review + opus final review + merge (same pattern as #1). **Push is deferred to the session-level deployment step** (it is bundled with the public-transition + claudebase/marketplace registration the user requested) — do not push from inside this plan execution.

---

## Self-Review (run against the spec)

**1. Spec coverage — the 7 deliverables:**
1. `evaluator.py` (parser + subprocess runner + `EvaluatorError`) → Tasks 2, 3. ✔
2. `decide_outcome` pure tree (pass_only vs score_improvement, B5), exhaustive per-branch → Task 4. ✔
3. B6 hybrid revert (config→git SHA recorded via `baseline_commit`/`last_kept_commit`; weights→`last_kept_checkpoint` pointer, keep advances / non-keep leaves, NO git op on weights) encoded in code+tests → Tasks 1 (pointer getter), 5 (`seed_ledger` invariant baseline + `record_iteration` + B6 tests incl. discard-leaves, ambiguous-leaves, no-weight-mutation, baseline-invariance). ✔
4. `ledger.json` + `results.tsv` + `decision-log.md` trio writers via omx_paths, atomic → Task 5. ✔
5. Committed Isaac Lab reference evaluator.sh (ships pass_only), via `reference_evaluator` getter → Tasks 1, 6. ✔
6. CLI `omx eval` (Claude-free, Bash-unit-testable) → Task 7. ✔
7. score↔policy coupling (score-less + score_improvement → ambiguous; + pass_only → keep) → Task 4 (decide tests) + Task 7 (CLI end-to-end). ✔

**2. Placeholder scan:** every code step contains complete runnable Python/Bash — no `...`, TODO, or `pass # implement`. The reference `evaluator.sh` is an HONEST documented stub (emits a fixed contract-valid line + comments showing the live-eval_dr slot) per the brief, NOT a placeholder; its test asserts the emitted JSON parses through `parse_evaluator_result`. ✔

**3. Type/name consistency:** `EvaluationRecord` is a plain dict throughout (matches state.py/ingest dict style). `pass` is Python bool, `score` omitted when None (mirrors `contracts.ts:198-200`). `last_kept_score` is float|None; `_comparable_score(prev,nxt)` true only when BOTH numeric (mirrors `runtime.ts:661-663`). `decide_outcome`/`record_iteration`/`seed_ledger`/`run_evaluator`/`parse_keep_policy`/`parse_evaluator_result` signatures are consistent across Tasks 2-7 and the CLI call sites. Atomic writes reuse `atomic_path`; JSON dumps use `indent=2, sort_keys=True` (matches state.py). `RESULTS_HEADER` byte-matches `AUTORESEARCH_RESULTS_HEADER` (runtime.ts:146). ✔

**4. Missing-getter scan:** `OmxError`, `reference_dir`, `reference_evaluator`, `checkpoint_pointer_json` all ADDED in Task 1 with failing tests FIRST, before any consumer (Tasks 5/6/7) uses them. No consumer references a getter that does not yet exist in task order. ✔

**5. Loud-fail audit:** `parse_evaluator_result` raises on bad JSON / non-bool pass / non-numeric score; `parse_keep_policy` raises on unknown string; `decide_outcome` raises on un-normalized keep_policy; `reference_evaluator` raises if the .sh is absent. No silent fallback. `run_evaluator`'s fault-tolerance is RECORD-not-swallow (parse_error captured, surfaced to the tree as evaluator-error → discard). ✔

**6. Regression:** `OmxPathError` reparenting to `(OmxError, ValueError)` preserves all 160 baseline `pytest.raises(ValueError)`/`(Exception)` sites; Task 1 Step 5 re-runs the full suite (expect 165) before any new behavior. Final suite expect **221 passed**. ✔
