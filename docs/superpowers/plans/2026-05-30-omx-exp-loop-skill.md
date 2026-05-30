# OMX build #6 — exp-loop skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `exp-loop` skill — a semi-autonomous analyze→design→eval→keep/discard→log→repeat loop — plus the small Claude-free core it orchestrates (a deadline ceiling, a pending-launch queue, and two CLI verbs), so that training launch is ALWAYS queued as a pending-approval artifact and NEVER auto-fired (design D4/B8).

**Architecture:** Three layers, smallest-first. (1) One new path getter `pending_launch_json(run_id)` in `omx_paths.py`. (2) A new pure-Python `omx_core/loop.py` with a deterministic deadline ceiling (caller injects "now" — no `datetime.now()` inside the testable functions, so tests are reproducible) and atomic loud-fail pending-launch queue IO. (3) Two Claude-free CLI verbs (`omx queue-launch`, `omx loop-status`) the skill uses so it never hand-writes a path. The loop's keep/discard, ledger, and evaluator logic are ALREADY built (#2 `decision.py`/`ledger.py`/`evaluator.py`/`omx eval`); exp-loop only orchestrates them. The skill (`skills/exp-loop/SKILL.md`) is the Claude-required orchestrator: the "leaving-work" deadline gates analyze/design/eval only; training launch is queued via `omx queue-launch`, never executed.

**Tech Stack:** Python 3.12 (stdlib only: `json`, `datetime`, `subprocess` already imported by siblings), pytest 9.x. No new third-party deps. Markdown skill file. Reuses `omx_paths` (getters + `atomic_path` + `OmxError`), `decision.py`, `ledger.py`, `evaluator.py`, `state.py` from builds #1/#2/#3.

---

## Context the implementer needs (read before starting)

This is build #6 of OMX (oh-my-experiments), a self-contained Claude Code plugin for analyzing RL experiment results and designing the next experiment. The repo root is `/workspace/oh-my-experiments`. The Python package lives in `omx-core/` (hyphen = dist dir) and imports as `omx_core` (underscore = package).

**CRITICAL environment traps (already burned on these):**
- Use `python3`, NOT `python` (`python` is an Isaac Sim wrapper in this Docker container).
- `pip install -e .` needs `--break-system-packages` (PEP 668; root Docker, safe). It is already installed editable — you should NOT need to reinstall.
- Run tests from the package dir: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/ -q`.
- Pyright `reportMissingImports(omx_core.*)` warnings are editable-install false positives — ignore them.
- Cache files are `.npz` (NOT parquet — pyarrow absent). Not relevant to this build but don't be surprised.

**What ALREADY exists and you MUST reuse (do not rebuild):**
- `omx_core/omx_paths.py` — `OmxPaths(root, profile=None)` with getters `run_dir(run_id)`, `results_tsv`, `ledger_json`, `decision_log`, `checkpoint_pointer_json(run_id)`, `state_json()`, plus `atomic_path(target)` (a context manager: `with atomic_path(target) as tmp: tmp.write_text(...)` writes to a `.tmp` sibling then `os.replace`s atomically), `OmxError` (base), `OmxPathError(OmxError, ValueError)`, and `validate_run_id`. `run_dir(run_id)` returns `self.omx_dir / "runs" / self._check_run_id(run_id)`.
- `omx_core/decision.py` — `parse_keep_policy(raw)->str` and `decide_outcome(keep_policy, last_kept_score, evaluation)->dict` (returns `{"decision","decision_reason","keep","evaluator","notes"}`). Already covers keep/discard/ambiguous/bootstrap (B5).
- `omx_core/ledger.py` — `seed_ledger(paths, run_id, *, baseline_commit, keep_policy)` and `record_iteration(paths, run_id, *, iteration, decision, candidate_checkpoint, candidate_commit, description)` (writes results.tsv + ledger.json + decision-log.md + checkpoint-pointer.json mirror, applies B6 pointer advance/leave).
- `omx_core/evaluator.py` — `run_evaluator(command, cwd, *, timeout=600)->dict` and `parse_evaluator_result(raw)->dict`, with `EvaluatorError(OmxError)`.
- `omx_core/state.py` — `load_state(paths)->dict` / `save_state(paths, state)` over `.omx/state.json`; `DEFAULT_STATE = {"omx_state_version":1, "active_loop":None, "current_phase":None, "session_id":None}`.
- `omx_core/cli.py` — the `omx` CLI. Has `_cmd_eval` (already has the NaN guard `_finite_clean` + `allow_nan=False` — DO NOT re-add a NaN guard; build #6 does not own one, it was completed in #3). Subparsers are wired in `build_parser()` via `sub.add_parser(...)` + `set_defaults(func=...)`. The dispatch entrypoint is `main()`.
- `skills/exp-analyze/SKILL.md` and `skills/exp-design/SKILL.md` — the two skills exp-loop orchestrates. exp-analyze writes `report.md`; exp-design reads it and writes `proposals/<proposal_id>.md` (`proposal_id = <YYYYMMDD-HHMMSS>-next`). Both end by saying their successor (#5 / #6) is the next step.

**Test baseline before you start:** `292 passed, 1 skipped`. Every task adds tests; the count only goes up.

**Design invariants you must honor (from `docs/design/2026-05-30-omx-experiment-harness-design.md`):**
- **D4/B8** — exp-loop NEVER auto-launches training. It queues the next launch as a `pending approval` artifact. The "leaving-work" deadline ceiling governs ONLY analyze/design/eval, not launch. There is no override path in v0.1.
- **B6** — config/hyperparam edits revert via git (ledger records `baseline_commit` + `last_kept_commit`); trained weights revert via the `last_kept_checkpoint` POINTER in `ledger.json` (keep advances, non-keep leaves; NO git/rm on weight files). `record_iteration` already does this — exp-loop just calls it.
- **path-SSOT (D8)** — every `.omx/` path comes from an `omx_paths` getter. No string-concatenated paths anywhere, including in the skill (the skill calls CLI verbs that resolve paths internally).
- **loud-fail** — malformed input raises (OmxError), never silently falls back.

---

## File Structure

| File | New/Mod | Responsibility |
|:--|:--|:--|
| `omx-core/omx_core/omx_paths.py` | Modify | +1 getter `pending_launch_json(run_id)` (runs-tree, like `checkpoint_pointer_json`). |
| `omx-core/omx_core/loop.py` | Create | Pure-Python loop helpers: `compute_deadline`, `deadline_passed` (deterministic, now-injected); `queue_pending_launch`, `read_pending_launch` (atomic loud-fail queue IO). NO launch execution. |
| `omx-core/omx_core/__init__.py` | Modify | Export the new loop functions. |
| `omx-core/omx_core/cli.py` | Modify | +2 verbs: `omx queue-launch` (write pending-launch via core), `omx loop-status` (read deadline + pending-launch + ledger pointer; Claude-free). |
| `omx-core/tests/test_loop.py` | Create | Unit tests for `loop.py` (deadline + queue IO). |
| `omx-core/tests/test_omx_paths.py` | Modify | +tests for `pending_launch_json`. |
| `omx-core/tests/test_cli.py` | Modify | +tests for `queue-launch` / `loop-status`. |
| `skills/exp-loop/SKILL.md` | Create | The Claude-required orchestrator (analyze→design→eval→keep/discard→log→repeat; deadline ceiling; launch queued never fired). |
| `.claude-plugin/plugin.json` | Modify | Add `exp-loop` to skills array (4 total). |
| `docs/HANDOFF.md` | Modify | Mark #6 done, point at #7. |

---

## Task 1: `pending_launch_json` path getter

**Files:**
- Modify: `omx-core/omx_core/omx_paths.py` (add a method after `checkpoint_pointer_json`, around line 226)
- Test: `omx-core/tests/test_omx_paths.py`

- [ ] **Step 1: Write the failing test**

Add to `omx-core/tests/test_omx_paths.py` (follow the existing test style in that file — it constructs `OmxPaths(root=tmp_path)` and checks `.name` / `.parent`):

```python
def test_pending_launch_json_under_run_dir(tmp_path):
    p = OmxPaths(root=tmp_path)
    target = p.pending_launch_json("run-42")
    assert target.name == "pending-launch.json"
    assert target.parent == p.run_dir("run-42")


def test_pending_launch_json_validates_run_id(tmp_path):
    p = OmxPaths(root=tmp_path)
    with pytest.raises(OmxPathError):
        p.pending_launch_json("../escape")
```

If `OmxPathError` / `pytest` are not already imported at the top of `test_omx_paths.py`, add the imports (check the file head first; they almost certainly are — other tests use them).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_omx_paths.py::test_pending_launch_json_under_run_dir -v`
Expected: FAIL with `AttributeError: 'OmxPaths' object has no attribute 'pending_launch_json'`

- [ ] **Step 3: Write minimal implementation**

In `omx-core/omx_core/omx_paths.py`, add this method immediately after `checkpoint_pointer_json` (it reuses `run_dir`, which already validates the run_id):

```python
    def pending_launch_json(self, run_id) -> Path:
        """runs/<run_id>/pending-launch.json — the next training launch QUEUED by
        exp-loop for human approval (B8). exp-loop NEVER fires a launch; it writes
        this artifact and stops. The human reads it, approves, and launches by
        hand. Run-bound, sits beside the ledger trio."""
        return self.run_dir(run_id) / "pending-launch.json"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_omx_paths.py -v -k pending_launch`
Expected: PASS (both new tests)

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/omx_core/omx_paths.py omx-core/tests/test_omx_paths.py
git commit -m "feat(omx-paths): add pending_launch_json run-tree getter for B8 launch queue

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: deadline ceiling helpers (`compute_deadline`, `deadline_passed`)

The "leaving-work" toggle is a max-runtime ceiling on the autonomous analyze/design/eval phases. OMC computes `deadlineAt = new Date(Date.now() + maxRuntimeMs)` (runtime.ts:971-972) and a stop-hook checks whether the deadline passed (persistent-mode/index.ts:1463-1474). We re-implement this as two PURE functions where the CALLER injects the current time as an ISO-8601 string — so tests are deterministic (no wall-clock dependency) and the functions never call `datetime.now()` themselves. The CLI layer (Task 5) is the only place that reads the real clock.

**Files:**
- Create: `omx-core/omx_core/loop.py`
- Test: `omx-core/tests/test_loop.py`

- [ ] **Step 1: Write the failing test**

Create `omx-core/tests/test_loop.py`:

```python
"""Tests for omx_core.loop — deadline ceiling + pending-launch queue (Claude-free)."""
import json

import pytest

from omx_core.loop import compute_deadline, deadline_passed
from omx_core.omx_paths import OmxError


def test_compute_deadline_adds_seconds():
    # 100 s after 2026-05-30T12:00:00+00:00 -> 12:01:40
    out = compute_deadline("2026-05-30T12:00:00+00:00", 100)
    assert out == "2026-05-30T12:01:40+00:00"


def test_compute_deadline_rejects_nonpositive():
    with pytest.raises(OmxError):
        compute_deadline("2026-05-30T12:00:00+00:00", 0)
    with pytest.raises(OmxError):
        compute_deadline("2026-05-30T12:00:00+00:00", -5)


def test_compute_deadline_rejects_bad_now():
    with pytest.raises(OmxError):
        compute_deadline("not-a-timestamp", 100)


def test_deadline_passed_true_when_now_after():
    assert deadline_passed("2026-05-30T12:00:00+00:00",
                           "2026-05-30T12:00:01+00:00") is True


def test_deadline_passed_false_when_now_before():
    assert deadline_passed("2026-05-30T12:00:00+00:00",
                           "2026-05-30T11:59:59+00:00") is False


def test_deadline_passed_true_at_exact_boundary():
    # at the deadline instant, the ceiling is reached (>=)
    assert deadline_passed("2026-05-30T12:00:00+00:00",
                           "2026-05-30T12:00:00+00:00") is True


def test_deadline_passed_rejects_bad_iso():
    with pytest.raises(OmxError):
        deadline_passed("2026-05-30T12:00:00+00:00", "garbage")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'omx_core.loop'`

- [ ] **Step 3: Write minimal implementation**

Create `omx-core/omx_core/loop.py` with ONLY the deadline helpers for now (the queue IO comes in Task 3):

```python
"""omx_core.loop — exp-loop's Claude-free core: a max-runtime deadline ceiling
and the pending-launch queue. NO launch execution lives here (design D4/B8):
exp-loop queues the next training launch for human approval and never fires it.

The deadline helpers are PURE and time-INJECTED — the caller passes the current
instant as an ISO-8601 string, so unit tests are deterministic and the functions
never read the wall clock. Only the CLI layer (cli.py _cmd_loop_status) reads the
real clock. This mirrors OMC runtime.ts:971-972 (deadlineAt = now + maxRuntimeMs)
and persistent-mode/index.ts:1463-1474 (deadline check), re-implemented, never
imported.
"""
from datetime import datetime, timedelta

from omx_core.omx_paths import OmxError


def _parse_iso(value, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise OmxError(f"{label} must be a non-empty ISO-8601 string, got {value!r}.")
    try:
        return datetime.fromisoformat(value)
    except ValueError as e:
        raise OmxError(f"{label} is not a valid ISO-8601 timestamp: {value!r}.") from e


def compute_deadline(now_iso: str, max_runtime_s: int) -> str:
    """Return the ISO-8601 instant `max_runtime_s` seconds after `now_iso`.

    This is the analyze/design/eval ceiling — NOT a launch trigger (D4/B8).
    Loud-fail on a non-positive runtime or an unparseable `now_iso`.
    """
    if not isinstance(max_runtime_s, int) or isinstance(max_runtime_s, bool) or max_runtime_s <= 0:
        raise OmxError(f"max_runtime_s must be a positive int, got {max_runtime_s!r}.")
    start = _parse_iso(now_iso, "now_iso")
    return (start + timedelta(seconds=max_runtime_s)).isoformat()


def deadline_passed(deadline_iso: str, now_iso: str) -> bool:
    """True iff `now_iso` is at or past `deadline_iso` (the ceiling is inclusive).

    Both args are loud-fail-parsed. exp-loop calls this between iterations to
    decide whether to stop the autonomous analyze/design/eval phase.
    """
    deadline = _parse_iso(deadline_iso, "deadline_iso")
    now = _parse_iso(now_iso, "now_iso")
    return now >= deadline
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_loop.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/omx_core/loop.py omx-core/tests/test_loop.py
git commit -m "feat(loop): add deterministic deadline ceiling helpers (time-injected, pure)

compute_deadline / deadline_passed re-implement OMC's max-runtime gate as pure
now-injected functions so the analyze/design/eval ceiling is unit-testable
without a wall clock. No launch trigger here (D4/B8).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: pending-launch queue IO (`queue_pending_launch`, `read_pending_launch`)

The queue artifact is the heart of B8: instead of firing the next training run, exp-loop WRITES a `pending-launch.json` describing what to launch, marked `pending approval`, and stops. The human reads it and launches by hand. The structure is fixed by the core (generic, deployable); the VALUES (launch delta, GPU gate) come from the proposal + the workspace profile.

**Files:**
- Modify: `omx-core/omx_core/loop.py` (append the queue functions)
- Test: `omx-core/tests/test_loop.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `omx-core/tests/test_loop.py`:

```python
from omx_core.loop import queue_pending_launch, read_pending_launch
from omx_core.omx_paths import OmxPaths


def test_queue_pending_launch_writes_artifact(tmp_path):
    p = OmxPaths(root=tmp_path)
    queue_pending_launch(
        p, "run-7",
        proposal_id="20260530-120000-next",
        launch_delta="set payload_cog_offset_xy_radius=0.05",
        gpu_gate="nvidia-smi shows GPU0 free",
        queued_at="2026-05-30T12:00:00+00:00",
    )
    target = p.pending_launch_json("run-7")
    assert target.exists()
    data = json.loads(target.read_text())
    assert data["status"] == "pending approval"
    assert data["proposal_id"] == "20260530-120000-next"
    assert data["launch_delta"] == "set payload_cog_offset_xy_radius=0.05"
    assert data["gpu_gate"] == "nvidia-smi shows GPU0 free"
    assert data["queued_at"] == "2026-05-30T12:00:00+00:00"


def test_queue_pending_launch_loud_fails_on_empty_proposal(tmp_path):
    p = OmxPaths(root=tmp_path)
    with pytest.raises(OmxError):
        queue_pending_launch(
            p, "run-7", proposal_id="  ", launch_delta="x",
            gpu_gate="g", queued_at="2026-05-30T12:00:00+00:00")


def test_queue_pending_launch_loud_fails_on_empty_delta(tmp_path):
    p = OmxPaths(root=tmp_path)
    with pytest.raises(OmxError):
        queue_pending_launch(
            p, "run-7", proposal_id="20260530-120000-next", launch_delta="",
            gpu_gate="g", queued_at="2026-05-30T12:00:00+00:00")


def test_read_pending_launch_roundtrips(tmp_path):
    p = OmxPaths(root=tmp_path)
    queue_pending_launch(
        p, "run-7", proposal_id="20260530-120000-next",
        launch_delta="x", gpu_gate="g", queued_at="2026-05-30T12:00:00+00:00")
    out = read_pending_launch(p, "run-7")
    assert out["proposal_id"] == "20260530-120000-next"
    assert out["status"] == "pending approval"


def test_read_pending_launch_returns_none_when_absent(tmp_path):
    p = OmxPaths(root=tmp_path)
    assert read_pending_launch(p, "run-7") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_loop.py -v -k pending_launch`
Expected: FAIL with `ImportError: cannot import name 'queue_pending_launch'`

- [ ] **Step 3: Write minimal implementation**

Append to `omx-core/omx_core/loop.py` (add `import json` and `OmxPaths, atomic_path` to the imports at the top — change the existing import line):

At the top, change the import block to:

```python
import json
from datetime import datetime, timedelta

from omx_core.omx_paths import OmxError, OmxPaths, atomic_path
```

Then append at the bottom of the file:

```python
def _require_nonempty(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OmxError(f"{label} must be a non-empty string, got {value!r}.")
    return value.strip()


def queue_pending_launch(paths: OmxPaths, run_id, *, proposal_id, launch_delta,
                         gpu_gate, queued_at) -> None:
    """Write runs/<run_id>/pending-launch.json marked 'pending approval' (B8).

    This is the ONLY thing exp-loop does with a launch — it queues it, never
    fires it. `proposal_id` ties back to the exp-design proposal; `launch_delta`
    is the one-line change vs the profile's launch.sh; `gpu_gate` is the
    nvidia-smi precondition the human must confirm; `queued_at` is an ISO-8601
    instant supplied by the caller (the CLI injects the real clock). All four
    are required and loud-fail when empty. Atomic write via atomic_path.
    """
    pid = _require_nonempty(proposal_id, "proposal_id")
    delta = _require_nonempty(launch_delta, "launch_delta")
    gate = _require_nonempty(gpu_gate, "gpu_gate")
    when = _require_nonempty(queued_at, "queued_at")
    target = paths.pending_launch_json(run_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "status": "pending approval",
        "proposal_id": pid,
        "launch_delta": delta,
        "gpu_gate": gate,
        "queued_at": when,
    }
    with atomic_path(target) as tmp:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))


def read_pending_launch(paths: OmxPaths, run_id):
    """Return the queued pending-launch dict, or None if nothing is queued.

    Loud-fail (OmxError) if the file exists but is not valid JSON — a corrupt
    queue must surface, never be silently treated as 'empty'."""
    target = paths.pending_launch_json(run_id)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text())
    except ValueError as e:
        raise OmxError(f"pending-launch.json for {run_id!r} is corrupt: {e}") from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_loop.py -v`
Expected: PASS (12 tests total: 7 deadline + 5 queue)

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/omx_core/loop.py omx-core/tests/test_loop.py
git commit -m "feat(loop): add pending-launch queue IO (B8 — queue never fire)

queue_pending_launch writes runs/<id>/pending-launch.json marked 'pending
approval'; read_pending_launch round-trips it (loud-fail on corrupt JSON).
This is the ONLY thing exp-loop does with a launch — it queues, never executes.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: export loop helpers from `omx_core`

**Files:**
- Modify: `omx-core/omx_core/__init__.py`
- Test: `omx-core/tests/test_core_import_safe.py` (verify the import-safety guard still passes with the new module)

- [ ] **Step 1: Write the failing test**

Add to `omx-core/tests/test_core_import_safe.py` (it already imports `omx_core` and asserts top-level names; mirror the existing assertion style):

```python
def test_loop_symbols_exported():
    import omx_core
    for name in ("compute_deadline", "deadline_passed",
                 "queue_pending_launch", "read_pending_launch"):
        assert hasattr(omx_core, name), f"omx_core.{name} not exported"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_core_import_safe.py::test_loop_symbols_exported -v`
Expected: FAIL with `AssertionError: omx_core.compute_deadline not exported`

- [ ] **Step 3: Write minimal implementation**

In `omx-core/omx_core/__init__.py`, add the import and extend `__all__`. Find the existing block (it already imports from `report`, `decision`, etc.) and add:

```python
from omx_core.loop import (
    compute_deadline,
    deadline_passed,
    queue_pending_launch,
    read_pending_launch,
)
```

Then add these four names to the `__all__` list (append to the existing list — do not replace it):

```python
    "compute_deadline",
    "deadline_passed",
    "queue_pending_launch",
    "read_pending_launch",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_core_import_safe.py -v`
Expected: PASS (all import-safety tests, including the new one)

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/omx_core/__init__.py omx-core/tests/test_core_import_safe.py
git commit -m "feat(core): export loop helpers (compute_deadline/deadline_passed/queue/read)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `omx queue-launch` + `omx loop-status` CLI verbs

These are the Claude-free seams the skill uses so it NEVER hand-writes a path or reads the clock itself. `queue-launch` injects the real clock (`datetime.now(timezone.utc).isoformat()`) and calls `queue_pending_launch`. `loop-status` reads the ledger pointer (via `read_pending_launch` + the checkpoint-pointer mirror) and, given `--deadline` + an injected/real `--now`, reports whether the ceiling passed — a single JSON the skill reads to decide "keep looping or stop".

**Files:**
- Modify: `omx-core/omx_core/cli.py`
- Test: `omx-core/tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Add to `omx-core/tests/test_cli.py` (follow the existing CLI test pattern: it runs `main(["verb", ...])` or invokes the module; check the file head for the exact helper — most tests call a `run_cli(args)` helper or `cli.main(argv)` and capture stdout via `capsys`). Use whatever the file already uses; the assertions:

```python
def test_queue_launch_writes_pending(tmp_path, capsys):
    rc = cli.main([
        "queue-launch", "--root", str(tmp_path), "--run-id", "run-9",
        "--proposal-id", "20260530-120000-next",
        "--launch-delta", "set radius=0.05",
        "--gpu-gate", "GPU0 free",
    ])
    assert rc == 0
    from omx_core.omx_paths import OmxPaths
    target = OmxPaths(root=tmp_path).pending_launch_json("run-9")
    assert target.exists()
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "pending approval"
    assert out["queued_at"]  # CLI injected a real timestamp


def test_loop_status_reports_deadline_and_queue(tmp_path, capsys):
    # queue something first
    cli.main([
        "queue-launch", "--root", str(tmp_path), "--run-id", "run-9",
        "--proposal-id", "20260530-120000-next",
        "--launch-delta", "set radius=0.05", "--gpu-gate", "GPU0 free",
    ])
    capsys.readouterr()  # drain
    rc = cli.main([
        "loop-status", "--root", str(tmp_path), "--run-id", "run-9",
        "--deadline", "2026-05-30T12:00:00+00:00",
        "--now", "2026-05-30T12:00:01+00:00",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["deadline_passed"] is True
    assert out["pending_launch"]["proposal_id"] == "20260530-120000-next"


def test_loop_status_no_deadline_is_none(tmp_path, capsys):
    rc = cli.main(["loop-status", "--root", str(tmp_path), "--run-id", "run-9"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["deadline_passed"] is None
    assert out["pending_launch"] is None
```

If `test_cli.py` imports the module differently (e.g. `from omx_core import cli`), match it. If it has no `cli.main` and instead uses `subprocess`, prefer adapting to the in-process `main(argv)` form — `build_parser()`/`main()` already accept argv; confirm by reading the file head.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_cli.py -v -k "queue_launch or loop_status"`
Expected: FAIL with argparse error (`invalid choice: 'queue-launch'`) → SystemExit, i.e. the verb isn't registered.

- [ ] **Step 3: Write minimal implementation**

In `omx-core/omx_core/cli.py`:

(a) Ensure these imports exist at the top (add what's missing — `datetime`/`timezone` and the loop functions):

```python
from datetime import datetime, timezone

from omx_core.loop import queue_pending_launch, read_pending_launch, deadline_passed
from omx_core.omx_paths import OmxPaths, OmxError
```

(`OmxPaths`/`OmxError` are very likely already imported — do not duplicate; just add `queue_pending_launch, read_pending_launch, deadline_passed` and the datetime import if absent.)

(b) Add the two command functions (place them near `_cmd_eval`, before `build_parser`):

```python
def _cmd_queue_launch(args) -> int:
    """Queue the next training launch as a pending-approval artifact (B8).

    NEVER launches — writes runs/<run_id>/pending-launch.json and prints it.
    queued_at is the real clock, injected here (the core stays time-pure)."""
    paths = OmxPaths(root=args.root)
    now = datetime.now(timezone.utc).isoformat()
    try:
        queue_pending_launch(
            paths, args.run_id,
            proposal_id=args.proposal_id, launch_delta=args.launch_delta,
            gpu_gate=args.gpu_gate, queued_at=now)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps(read_pending_launch(paths, args.run_id)))
    return 0


def _cmd_loop_status(args) -> int:
    """Report loop status as one JSON: whether the deadline ceiling passed and
    what (if anything) is queued for launch. Claude-free; the skill reads this
    to decide stop-or-continue. --now defaults to the real clock; pass it
    explicitly for deterministic tests."""
    paths = OmxPaths(root=args.root)
    now = args.now or datetime.now(timezone.utc).isoformat()
    passed = None
    if args.deadline:
        try:
            passed = deadline_passed(args.deadline, now)
        except OmxError as e:
            raise SystemExit(str(e))
    try:
        pending = read_pending_launch(paths, args.run_id)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps({
        "run_id": args.run_id,
        "now": now,
        "deadline": args.deadline,
        "deadline_passed": passed,
        "pending_launch": pending,
    }))
    return 0
```

(c) Register both subparsers inside `build_parser()` (after the existing `report-parse` block, following the same `sub.add_parser(...)` + `set_defaults` pattern):

```python
    pq = sub.add_parser("queue-launch",
                        help="queue the next training launch as pending-approval (B8; never fires)")
    pq.add_argument("--root", required=True)
    pq.add_argument("--run-id", required=True)
    pq.add_argument("--proposal-id", required=True)
    pq.add_argument("--launch-delta", required=True)
    pq.add_argument("--gpu-gate", required=True)
    pq.set_defaults(func=_cmd_queue_launch)

    pl = sub.add_parser("loop-status",
                        help="report deadline-ceiling + pending-launch as JSON (Claude-free)")
    pl.add_argument("--root", required=True)
    pl.add_argument("--run-id", required=True)
    pl.add_argument("--deadline", default=None,
                    help="ISO-8601 deadline; omit to skip the ceiling check")
    pl.add_argument("--now", default=None,
                    help="ISO-8601 now (defaults to the real clock; pass for tests)")
    pl.set_defaults(func=_cmd_loop_status)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/test_cli.py -v -k "queue_launch or loop_status"`
Expected: PASS (3 tests)

Then run the FULL suite to confirm no regression:
Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/ -q`
Expected: all pass (baseline 292 + new tests; ≈307 passed, 1 skipped)

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/omx_core/cli.py omx-core/tests/test_cli.py
git commit -m "feat(cli): add queue-launch + loop-status verbs (Claude-free loop seams)

queue-launch injects the real clock and writes the pending-approval artifact;
loop-status reports deadline_passed + pending_launch as one JSON the skill reads
to decide stop-or-continue. Never launches (B8).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `exp-loop` skill — the orchestrator

This is the Claude-required body. It ties the loop together: it calls exp-analyze and exp-design (the two prior skills), runs the evaluator via `omx eval`, records each iteration via the core, and — when a next experiment is warranted — QUEUES the launch via `omx queue-launch` and STOPS. The "leaving-work" deadline gates the autonomous analyze/design/eval phases only; training launch is always a human gate.

**Files:**
- Create: `skills/exp-loop/SKILL.md`

- [ ] **Step 1: Write the skill file**

There is no failing-test step for a markdown skill (it has no executable assertions). The "test" is structural review (the spec/quality reviewers check it against the design + sibling skills). Write `skills/exp-loop/SKILL.md` with EXACTLY this content:

````markdown
---
name: exp-loop
description: Run a semi-autonomous experiment loop — analyze the latest run, design the next experiment, evaluate a candidate, keep or discard it, log the decision, and repeat until a deadline or a stop condition. The "leaving-work" deadline governs only the analyze/design/eval phases; the next TRAINING LAUNCH is queued as a pending-approval artifact and NEVER auto-fired. Use when the user says "run the analyze→design→eval loop", "퇴근할 거니까 알아서 분석하고 다음 실험까지 큐에 넣어둬", "iterate on this experiment automatically", "keep evaluating candidates and keep the best". Triggers on "experiment loop", "auto-iterate", "다음 실험까지 돌려놔", "loop until".
argument-hint: "[--root <dir>] <run_id> [--max-runtime <seconds>]"
---

# exp-loop — semi-autonomous analyze→design→eval→keep/discard→log loop

## Overview

`exp-loop` chains the OMX skills into one supervised loop over a single run:

```
analyze (exp-analyze) -> design (exp-design) -> evaluate candidate (omx eval)
   -> keep/discard (omx decision via the core) -> log the iteration (ledger)
   -> queue the next launch (pending approval) -> STOP for human, or repeat
```

It NEVER launches training (design D4/B8). The "leaving-work" deadline is a
ceiling on the AUTONOMOUS phases (analyze/design/eval). The next training run is
always written to `runs/<run_id>/pending-launch.json` as `pending approval` for
the human to fire by hand. This honors the repo rule "훈련 종료/시작은 유저가
직접" with no override path.

**Announce at start:** "Using exp-loop to run the analyze→design→eval loop; training launch will be queued for your approval, never fired."

## Preconditions (check, don't assume)

1. A profile exists at `.omx/profile/` (run `exp-init` first if not). You need
   `metrics.yaml` (for `output_root` + the metric vocabulary) and `evaluator.sh`
   (the eval command) — both written by exp-init.
2. A `run_id` is given (the experiment to iterate on). If absent, ask for it and STOP.
3. The run has at least one analyzable result (an eval summary / training log the
   profile's adapters can ingest). If there is nothing to analyze, say so and STOP.

If any precondition is unmet, state exactly what is missing and STOP. Never
fabricate a run or invent an evaluator.

## Session id (scratch isolation, B2)

Resolve a session id once: `omx session-id` (it applies `--session-id` flag →
`OMX_SESSION_ID` env → autogen). Pass it to exp-analyze when you delegate.

## The deadline ceiling (the "leaving-work" toggle)

If the user gives `--max-runtime <seconds>` (or says "퇴근할 거니까"), set a
ceiling. Compute it ONCE at the start:

```bash
NOW=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
# the core computes the deadline; you store it for the loop
```

Then BEFORE each iteration, check the ceiling with the core (never eyeball the clock):

```bash
omx loop-status --root <root> --run-id <run_id> --deadline <deadline_iso>
```

If its JSON shows `"deadline_passed": true`, STOP the autonomous loop (do NOT
start another analyze/design/eval pass). The deadline NEVER triggers a launch —
it only stops analysis. With no `--max-runtime`, run exactly ONE iteration then
stop and report (a single supervised pass is the safe default).

## One iteration

### 1. Analyze
Delegate to `exp-analyze` for `<run_id>` (it writes `report.md` + promoted plots
to the permanent tree and emits evidence-tagged findings). Capture the
`analysis_id` it reports.

### 2. Design
Delegate to `exp-design` with that `report.md` (`<run_id>` + `<analysis_id>`). It
runs the 3-lane diagnosis and writes a `proposals/<proposal_id>.md` (the
discriminating probe = the next experiment), `pending approval`. Capture the
`proposal_id`.

### 3. Evaluate the current candidate (if one exists)
A "candidate" here is an already-trained checkpoint the human produced for this
run (exp-loop does NOT train). If the profile's `evaluator.sh` can grade the
current checkpoint, run it through the core (this is the single source of the
pass/score verdict — never eyeball a metric):

```bash
omx eval --command 'bash .omx/profile/evaluator.sh' --cwd <project_dir> \
    --keep-policy <pass_only|score_improvement> --last-kept-score <prev_or_omit>
```

The JSON includes a `decision` block (`keep`/`discard`/`ambiguous`/`bootstrap`)
when `--keep-policy` is set. That decision is authoritative. If there is no new
candidate to grade (e.g. this is the very first analysis pass), skip evaluation
and go straight to queuing the next launch.

### 4. Record the iteration (keep/discard target = B6)
The core has already applied the keep/discard pointer rule inside the ledger.
Record this iteration through the ledger writer (config reverts via git; weights
revert via the `last_kept_checkpoint` pointer — keep advances, non-keep leaves;
NO git/rm on weight files). You do NOT git-revert or delete any checkpoint
yourself in v0.1 — the ledger pointer + decision-log is the record; physical
checkpoint GC is out of scope (design §9). If a config edit was made and the
decision is `discard`, tell the user the exact `git revert`/`git checkout`
command to unwind to `baseline_commit` (from `ledger.json`) — but do NOT run it
unless they explicitly approve (minimum-change revert, repo rule).

### 5. Queue the next launch (NEVER fire it — B8)
The proposal from step 2 is the next experiment. Queue it for human approval:

```bash
omx queue-launch --root <root> --run-id <run_id> \
    --proposal-id <proposal_id> \
    --launch-delta "<the one-line change vs profile launch.sh, from the proposal>" \
    --gpu-gate "<the nvidia-smi precondition, e.g. 'GPU0 free per nvidia-smi'>"
```

This writes `runs/<run_id>/pending-launch.json` marked `pending approval`. STOP
here for the launch. You have NOT trained anything. Tell the user the proposal +
the queued launch, and that THEY must approve and run the training command.

### 6. Loop or stop
If a deadline is set and `omx loop-status` says it has NOT passed AND there is a
fresh candidate to analyze next, repeat from step 1. Otherwise STOP.

## Hard constraints (never violate)

- NEVER launch or start a training run. exp-loop only QUEUES launches via
  `omx queue-launch`. No `bash launch.sh`, no training subprocess, ever (D4/B8).
- NEVER auto-run a `git revert`/`git reset`/`rm` on weights or config. Surface
  the exact command; the human runs it (minimum-change revert rule).
- NEVER hand-write a `.omx/` path. Queue/status/eval all go through the `omx`
  CLI verbs, which resolve paths via the core (path-SSOT).
- NEVER invent a verdict. The pass/score decision comes ONLY from `omx eval`'s
  JSON (the evaluator contract), and the keep/discard from its `decision` block.
- The deadline ceiling gates ONLY analyze/design/eval — it is NEVER a launch
  trigger.
- Respond to the user in Korean (repo rule); keep skill/code/markdown in English.

## When done

Report, in Korean to the user:
- where the analysis report and proposal are (permanent tree paths),
- the keep/discard decision(s) and the reason (from the decision-log),
- that the next launch is QUEUED at `runs/<run_id>/pending-launch.json` as
  **pending approval — not launched**, and the exact training command they should
  run after approving.

This is the last skill in the OMX set. There is no successor loop to start.
````

- [ ] **Step 2: Verify the skill is well-formed**

Run: `cd /workspace/oh-my-experiments && head -5 skills/exp-loop/SKILL.md`
Expected: shows the YAML front-matter (`---` / `name: exp-loop` / `description:` ...).

Also confirm no accidental path leak (no absolute machine paths or private repo names in the shipped skill — placeholders only):
Run: `grep -nE "/workspace|luckkim123|/root/" skills/exp-loop/SKILL.md`
Expected: NO output (zero matches). If anything matches, replace it with a placeholder (`<root>`, `<project_dir>`, etc.) before committing.

- [ ] **Step 3: Commit**

```bash
cd /workspace/oh-my-experiments
git add skills/exp-loop/SKILL.md
git commit -m "feat(exp-loop): add the analyze->design->eval loop skill (launch queued, never fired)

Orchestrates exp-analyze + exp-design + omx eval/decision/ledger into one
supervised loop. The leaving-work deadline gates only analyze/design/eval; the
next training launch is queued as pending-approval and NEVER auto-fired (D4/B8).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: register exp-loop in plugin.json + update HANDOFF

**Files:**
- Modify: `.claude-plugin/plugin.json`
- Modify: `docs/HANDOFF.md`

- [ ] **Step 1: Read the current plugin.json skills array**

Run: `cd /workspace/oh-my-experiments && cat .claude-plugin/plugin.json`
Expected: `skills` array currently lists exactly three entries: `"./skills/exp-init/"`, `"./skills/exp-analyze/"`, `"./skills/exp-design/"`.

- [ ] **Step 2: Add exp-loop to the skills array**

Edit `.claude-plugin/plugin.json` so the skills array becomes (preserve the file's exact formatting/indentation — only add the one entry):

```json
  "skills": [
    "./skills/exp-init/",
    "./skills/exp-analyze/",
    "./skills/exp-design/",
    "./skills/exp-loop/"
  ]
```

- [ ] **Step 3: Verify plugin.json is valid JSON**

Run: `cd /workspace/oh-my-experiments && python3 -c "import json; d=json.load(open('.claude-plugin/plugin.json')); assert d['skills'][-1]=='./skills/exp-loop/'; print('ok', d['skills'])"`
Expected: `ok ['./skills/exp-init/', './skills/exp-analyze/', './skills/exp-design/', './skills/exp-loop/']`

- [ ] **Step 4: Update HANDOFF.md**

In `docs/HANDOFF.md`, add a `#6 exp-loop — DONE` bullet next to the existing `#5 exp-design — DONE` bullet (mirror its style/length), recording: branch name, what was built (the `pending_launch_json` getter + `loop.py` deadline/queue helpers + `queue-launch`/`loop-status` verbs + `exp-loop/SKILL.md`), the new test count, plugin.json now at 4 skills, that the #2 NaN guard was already done in #3 (NOT touched here), and NEXT = #7 (final). Also update the "다음에 할 일" / build-order line so #6 is no longer "next".

- [ ] **Step 5: Run the full suite one last time**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/ -q`
Expected: all pass (≈307 passed, 1 skipped — the exact number is baseline 292 + the new tests).

- [ ] **Step 6: Commit**

```bash
cd /workspace/oh-my-experiments
git add .claude-plugin/plugin.json docs/HANDOFF.md
git commit -m "feat(plugin): register exp-loop skill (4 skills) + update handoff for #6 done

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## FINAL: cross-cutting review (after all 7 tasks)

Dispatch a final opus code-reviewer over the whole #6 diff. Review lenses (all must PASS):

1. **Boundary integrity** — `loop.py` is pure (deadline functions are time-injected, no `datetime.now()` inside them; only `cli.py` reads the real clock). The core has ZERO launch-execution code.
2. **Hard-gate safety (D4/B8)** — there is no code path anywhere in #6 (core, CLI, or skill) that executes a training command. The skill only ever calls `omx queue-launch`. Grep the diff for `subprocess`, `bash launch`, `os.system`, `Popen` outside `evaluator.run_evaluator` (the eval path, which is allowed) — confirm none launch training.
3. **B6 fidelity** — keep/discard goes through `record_iteration` (already built); #6 adds NO new weight-file git/rm op. The skill surfaces the revert command but never runs it.
4. **path-SSOT (D8)** — every `.omx/` path in #6 comes from an `omx_paths` getter; the skill hand-writes no path (it shells to the CLI verbs).
5. **loud-fail** — `compute_deadline`/`deadline_passed`/`queue_pending_launch`/`read_pending_launch` all raise `OmxError` on bad input; none silently fall back. `read_pending_launch` loud-fails on corrupt JSON (does not treat corrupt as empty).
6. **Repo discipline** — no absolute paths / private repo names in shipped content (skill + reference); commit trailers present; tests actually exercise the new branches.

If the reviewer flags Critical/Important issues, the implementer fixes them (same subagent), the reviewer re-reviews, repeat until MERGE_READY. Then use `superpowers:finishing-a-development-branch` (merge to local main, do NOT push — push is user-gated; the prior 11 commits are also unpushed pending user authorization).

---

## Self-review (run before handing off to execution)

**1. Spec coverage** (design §4 exp-loop row + §8 #6 + D4/B8/B6 + §9 carry):
- analyze→design→eval→keep/discard→log→repeat loop → Task 6 (skill orchestrates) ✅
- "leaving-work" toggle gates analyze/design/eval only → Task 2 (deadline ceiling) + Task 6 (skill uses it, never for launch) ✅
- training launch queued, never fired (D4/B8) → Task 3 (queue IO) + Task 5 (`queue-launch` verb) + Task 6 (skill queues only) ✅
- keep/discard target = config-git + checkpoint-pointer (B6) → reuses `record_iteration` (built #2); skill surfaces revert command, never runs it ✅
- outputs `.omx/runs/<id>/{results.tsv, ledger.json, decision-log.md, checkpoint-pointer.json}` → all built #2; +`pending-launch.json` (Task 1 getter + Task 3 writer) ✅
- #2 NaN guard → ALREADY DONE in #3 (`_cmd_eval` has `_finite_clean`+`allow_nan=False`); explicitly NOT re-done here (noted in Task 7 HANDOFF + FINAL) ✅
- 1-GPU sequential (design §9) → skill's nvidia-smi gate is in the queued artifact's `gpu_gate`; loop is sequential by construction (one run, one iteration at a time) ✅
- registry/wiki "쓸수록 특화" → per the user's confirmation, the seed already exists (`registry/findings/`); #6 does NOT build a new wiki layer (scope guard) ✅

**2. Placeholder scan:** no "TBD"/"implement later"/"add error handling" — every code step shows complete code; the skill file is given in full. ✅

**3. Type consistency:**
- `pending_launch_json(run_id)` — same name in Task 1 (getter), Task 3 (`queue_pending_launch`/`read_pending_launch` call it), Task 5 (CLI). ✅
- `queue_pending_launch(paths, run_id, *, proposal_id, launch_delta, gpu_gate, queued_at)` — identical signature in Task 3 (def), Task 5 (call). ✅
- `compute_deadline(now_iso, max_runtime_s)` / `deadline_passed(deadline_iso, now_iso)` — identical in Task 2 (def + tests) and Task 5 (`deadline_passed` call). ✅
- pending-launch JSON keys (`status`, `proposal_id`, `launch_delta`, `gpu_gate`, `queued_at`, `schema_version`) — same in Task 3 writer + tests, Task 5 tests. ✅
- `OmxError` is the loud-fail base used everywhere (imported from `omx_paths`). ✅
