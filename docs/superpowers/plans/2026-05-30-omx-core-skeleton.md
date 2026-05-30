# OMX Core Skeleton (build-order #1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Claude-free core of OMX — ingest adapters (eval-summary + long-form CSV, with WandB/TB stubs), a reduce layer (summarize / downsample / headless plot / npz cache), a minimal `.omx/` state file, and an `omx` CLI — all routing every path through the `omx_paths.py` single source of truth from build-order #0.

**Architecture:** Pure-Python package `omx_core` (already holds `omx_paths.py`). New subpackages `ingest/` and `reduce/`, plus `state.py` and `cli.py`. Ingest normalizes any source into one container `IngestResult` (long-form `SummaryRecord` rows + named time-series arrays). Reduce consumes `IngestResult`: exact aggregates via pandas groupby (the repo's CV = std/mean rule), trajectory downsampling, headless matplotlib (`Agg`) PNG generation, and a numpy `.npz` derived-data cache. The `omx` CLI exposes the Claude-free verbs `omx ingest` / `omx reduce` so they are unit-testable from Bash with zero Claude/Isaac dependency.

**Tech Stack:** Python 3.12, stdlib + numpy 1.26 + pandas 3.0 + matplotlib 3.10 (Agg backend) + pyyaml. NO pyarrow (cache uses `.npz`). NO network, NO Claude, NO Isaac Sim. Tests: pytest with fixture files mirroring real eval_dr `summary.json` / `data_*.npz` schema.

---

## Scope & ground-truth (read before starting)

**Build-order #1 owns exactly:** ingest + reduce + `omx` CLI + minimal `state.json` + a one-line `cache_path` fix in the #0 module. It does **NOT** own: the evaluator-contract runner (build #2), exp-init/analyze/design/loop skills (builds #3-#6), `report.md` / `manifest.json` writers in the permanent tree (those are exp-analyze, build #4). The permanent-tree getters from #0 stay unused here — #1 writes only inside `.omx/` (cache, scratch) and prints to stdout.

**Verified real-data schema (do not re-derive — confirmed against `/workspace/constrained-albc/.../eval/static_.../`):**

1. **`summary.json`** — nested dict `{dr_level: {axis: {field: float}}}`:
   - `dr_level` ∈ `{"none", "soft", "medium", "hard"}`
   - `axis` ∈ `{"roll", "pitch", "vx", "vy", "vz", "yaw", "att_norm"}` (each a dict) **plus** `"survival_pct"` (a float scalar, NOT a dict — must be handled as a run-level record).
   - `roll/pitch/vx/vy/vz/yaw` carry **15 fields**: `os_env_mean, os_env_std, os_env_median, os_env_q90, us_env_mean, us_env_std, n_gt20, n_gt40, n_us_lt_minus20, rise_time, rise_time_std, ss_error, ss_error_std, ss_jitter, ss_jitter_std`.
   - `att_norm` carries **only 4 fields**: `ss_error, ss_error_std, ss_jitter, ss_jitter_std`. The adapter MUST tolerate this asymmetry (just emits fewer rows; never assumes all axes share a field set).

2. **`data_*.npz`** (siblings: `data_none.npz`, `data_soft.npz`, `data_medium.npz`, `data_hard.npz`) — 19 named arrays. Trajectories are `(7750, 4)` = `(timesteps, n_envs)`: `actual_roll_deg, actual_pitch_deg, error_roll, error_pitch, lin_vel_x, lin_vel_y, lin_vel_z, lin_vel_norm, yaw_rate, action_magnitude, terminated(bool)`. Targets are `(7750,)`: `time, target_roll_deg, target_pitch_deg, target_vx, target_vy, target_vz, target_yaw_rate`. Plus `time_to_failure (4,)`.

3. **Library reality:** `pyarrow` is **NOT installed**; `numpy/pandas/matplotlib/yaml` are. Therefore the `.omx/runs/<id>/cache/` files use numpy `.npz`, not parquet. This requires a one-line change to `omx_paths.cache_path` (Task 1). Design §10.2 named "parquet" as an example; the locked principle is "re-derivable cache", and self-containment (D1/D2 minimal dependency surface) is better served by stdlib+numpy.

**`omx_paths.py` public API #1 consumes (from #0, do not change except Task 1):**
- `OmxPaths(root, profile=None)` with `.cache_path(run_id, *, source, metric)`, `.scratch_plots(*, session_id)`, `.scratch_py(*, session_id)`, `.scratch_notes(*, session_id)`, `.state_json()`, `.run_dir(run_id)`.
- module helpers `resolve_session_id(explicit=None, env=None, autogen=None)`, `atomic_path(target)` (context manager → yields a `.tmp` path, `os.replace` on clean exit), `atomic_dir(target)`.
- `Profile` (frozen dataclass with `metrics/views/aggs/sources` frozensets + `run_id_regex`); `OmxPathError`.

**Profile vocab note (B1 two-tier):** `cache_path` validates `source`/`metric` against `Profile.sources`/`Profile.metrics` only when a `Profile` is attached; with `profile=None` (the #1 test default) it is structural-only (token regex `[a-z0-9][a-z0-9_]*`). So all #1 tests run profile-free and still exercise the real getters. Use lowercase tokens like `source="eval_summary"`, `metric="ss_error"` in tests — they pass the structural token regex.

**Natural checkpoint:** Tasks 1-6 (foundation + ingest) form a coherent half; Tasks 7-11 (reduce + CLI) the other. subagent-driven-development executes continuously, but if a blocker appears, end-of-Task-6 is the clean review point.

---

## File Structure

| File | Responsibility |
|:--|:--|
| `omx-core/omx_core/omx_paths.py` | **(modify, Task 1)** cache extension `.parquet` → `.npz`. |
| `omx-core/omx_core/state.py` | **(create, Task 2)** `.omx/state.json` schema + atomic load/save. |
| `omx-core/omx_core/ingest/__init__.py` | **(create, Task 3)** re-exports `IngestResult, SummaryRecord, IngestAdapter`. |
| `omx-core/omx_core/ingest/base.py` | **(create, Task 3)** containers + `IngestAdapter` ABC. |
| `omx-core/omx_core/ingest/eval_summary.py` | **(create, Task 4)** `EvalSummaryAdapter` (nested `summary.json`). |
| `omx-core/omx_core/ingest/csv_longform.py` | **(create, Task 5)** `LongFormCsvAdapter` (flat CSV). |
| `omx-core/omx_core/ingest/stubs.py` | **(create, Task 6)** `WandbAdapter`, `TensorboardAdapter` (signposted `NotImplementedError`). |
| `omx-core/omx_core/reduce/__init__.py` | **(create, Task 7)** re-exports reduce verbs. |
| `omx-core/omx_core/reduce/summarize.py` | **(create, Task 7)** long-form → DataFrame, CV = std/mean. |
| `omx-core/omx_core/reduce/series.py` | **(create, Task 8)** `load_npz`, `downsample`. |
| `omx-core/omx_core/reduce/plot.py` | **(create, Task 9)** headless `Agg` line/bar PNG. |
| `omx-core/omx_core/reduce/cache.py` | **(create, Task 10)** npz cache read/write via `omx_paths`. |
| `omx-core/omx_core/cli.py` | **(create, Task 11)** `omx ingest` / `omx reduce` argparse entry. |
| `omx-core/pyproject.toml` | **(modify, Tasks 1,11)** add deps (numpy/pandas/matplotlib/pyyaml) + `[project.scripts] omx`. |
| `omx-core/tests/fixtures/` | **(create, Task 4)** `summary.json`, `data_none.npz`, `metrics_long.csv` shrunk fixtures. |
| `omx-core/tests/test_*.py` | one test module per source file. |

DRY: ingest produces `IngestResult`; reduce only ever consumes `IngestResult` or raw arrays — no source-format knowledge leaks into reduce. YAGNI: no generic JSON adapter (it would equal eval-summary); no parquet; no state fields beyond what #6 will fill.

---

### Task 1: Fix cache extension parquet → npz (touch #0 artifact)

**Files:**
- Modify: `omx-core/omx_core/omx_paths.py:168`
- Modify: `omx-core/pyproject.toml` (add runtime deps)
- Test: `omx-core/tests/test_omx_paths.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `omx-core/tests/test_omx_paths.py`:

```python
def test_cache_path_uses_npz_extension(tmp_path):
    from omx_core.omx_paths import OmxPaths
    p = OmxPaths(tmp_path)
    out = p.cache_path("run01", source="eval_summary", metric="ss_error")
    assert out.name == "eval_summary__ss_error.npz"
    assert out.suffix == ".npz"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_omx_paths.py::test_cache_path_uses_npz_extension -v`
Expected: FAIL — `assert '...parquet' == '...npz'` (current code emits `.parquet`).

- [ ] **Step 3: Make the change**

In `omx-core/omx_core/omx_paths.py`, line 168, change:

```python
        return self.run_dir(run_id) / "cache" / f"{src}__{met}.parquet"
```

to:

```python
        return self.run_dir(run_id) / "cache" / f"{src}__{met}.npz"
```

- [ ] **Step 4: Add runtime dependencies to pyproject**

In `omx-core/pyproject.toml`, find the `[project]` table and set `dependencies` (create the key if absent):

```toml
dependencies = [
    "numpy>=1.26",
    "pandas>=2.0",
    "matplotlib>=3.8",
    "pyyaml>=6.0",
]
```

- [ ] **Step 5: Run the full suite to verify nothing broke**

Run: `cd omx-core && python3 -m pytest tests/ -q`
Expected: PASS (111 passed — the 110 from #0 plus the new one).

- [ ] **Step 6: Commit**

```bash
git add omx-core/omx_core/omx_paths.py omx-core/pyproject.toml omx-core/tests/test_omx_paths.py
git commit -m "fix(omx_paths): cache extension parquet -> npz (pyarrow absent; #1 reality)

pyarrow is not installed and RL trajectories are uniform float matrices with
little columnar benefit; source data is already .npz. Adds numpy/pandas/
matplotlib/pyyaml as omx-core runtime deps (build-order #1)."
```

---

### Task 2: `.omx/state.json` schema + atomic load/save

**Files:**
- Create: `omx-core/omx_core/state.py`
- Test: `omx-core/tests/test_state.py`

- [ ] **Step 1: Write the failing test**

Create `omx-core/tests/test_state.py`:

```python
import json
from omx_core.omx_paths import OmxPaths
from omx_core.state import load_state, save_state, DEFAULT_STATE


def test_load_missing_returns_default_copy(tmp_path):
    p = OmxPaths(tmp_path)
    st = load_state(p)
    assert st == DEFAULT_STATE
    # must be a copy, not the module-level dict (mutating it must not poison defaults)
    st["active_loop"] = "x"
    assert DEFAULT_STATE["active_loop"] is None


def test_save_then_load_roundtrip(tmp_path):
    p = OmxPaths(tmp_path)
    st = load_state(p)
    st["current_phase"] = "analyze"
    st["session_id"] = "20260530-101010-42"
    save_state(p, st)
    again = load_state(p)
    assert again["current_phase"] == "analyze"
    assert again["session_id"] == "20260530-101010-42"
    assert again["omx_state_version"] == 1


def test_save_is_atomic_no_tmp_left(tmp_path):
    p = OmxPaths(tmp_path)
    save_state(p, load_state(p))
    cache_dir = p.state_json().parent
    leftovers = [x.name for x in cache_dir.iterdir() if x.name.endswith(".tmp")]
    assert leftovers == []


def test_save_writes_valid_json(tmp_path):
    p = OmxPaths(tmp_path)
    save_state(p, load_state(p))
    data = json.loads(p.state_json().read_text())
    assert data["omx_state_version"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.state'`.

- [ ] **Step 3: Write the implementation**

Create `omx-core/omx_core/state.py`:

```python
"""omx_core.state — the single .omx/state.json mode-state file.

Build-order #1 defines the schema and atomic IO; the loop (build #6) fills the
fields. Kept minimal on purpose (YAGNI): only the keys design 10.2 names.
"""
import copy
import json

from omx_core.omx_paths import OmxPaths, atomic_path

# design 10.2: state.json holds OMX mode state (active loop?, current_phase, session_id)
DEFAULT_STATE = {
    "omx_state_version": 1,
    "active_loop": None,
    "current_phase": None,
    "session_id": None,
}


def load_state(paths: OmxPaths) -> dict:
    """Return the persisted state, or a fresh copy of DEFAULT_STATE if absent."""
    target = paths.state_json()
    if not target.exists():
        return copy.deepcopy(DEFAULT_STATE)
    return json.loads(target.read_text())


def save_state(paths: OmxPaths, state: dict) -> None:
    """Atomically write state to .omx/state.json (parents created, .tmp + os.replace)."""
    target = paths.state_json()
    target.parent.mkdir(parents=True, exist_ok=True)
    with atomic_path(target) as tmp:
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd omx-core && python3 -m pytest tests/test_state.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add omx-core/omx_core/state.py omx-core/tests/test_state.py
git commit -m "feat(state): .omx/state.json schema + atomic load/save (build-order #1)

Minimal mode-state file (design 10.2). Schema versioned; loop (#6) fills fields.
load returns a deep copy of DEFAULT_STATE when absent; save uses atomic_path."
```

---

### Task 3: Ingest containers + `IngestAdapter` ABC

**Files:**
- Create: `omx-core/omx_core/ingest/__init__.py`
- Create: `omx-core/omx_core/ingest/base.py`
- Test: `omx-core/tests/test_ingest_base.py`

- [ ] **Step 1: Write the failing test**

Create `omx-core/tests/test_ingest_base.py`:

```python
import numpy as np
import pytest
from omx_core.ingest import IngestResult, SummaryRecord, IngestAdapter


def test_summary_record_is_frozen():
    r = SummaryRecord(dr_level="none", axis="roll", field="ss_error", value=0.5)
    with pytest.raises(Exception):
        r.value = 9.0  # frozen dataclass


def test_summary_record_axis_may_be_none_for_run_level_scalar():
    r = SummaryRecord(dr_level="none", axis=None, field="survival_pct", value=100.0)
    assert r.axis is None
    assert r.field == "survival_pct"


def test_ingest_result_defaults_are_independent():
    a = IngestResult()
    b = IngestResult()
    a.summary.append(SummaryRecord("none", "roll", "ss_error", 0.1))
    a.series["x"] = np.arange(3)
    a.meta["k"] = "v"
    assert b.summary == [] and b.series == {} and b.meta == {}  # no shared mutable default


def test_adapter_is_abstract():
    with pytest.raises(TypeError):
        IngestAdapter()  # cannot instantiate ABC with abstract methods


def test_concrete_adapter_must_implement_both_methods():
    class Half(IngestAdapter):
        def can_handle(self, path):  # missing ingest()
            return True
    with pytest.raises(TypeError):
        Half()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_ingest_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.ingest'`.

- [ ] **Step 3: Write the implementation**

Create `omx-core/omx_core/ingest/base.py`:

```python
"""omx_core.ingest.base — normalized ingest containers + adapter contract.

Every source (eval_dr summary.json, CSV, WandB, TB) is normalized into ONE
container, IngestResult, so the reduce layer never learns a source format.
- summary: long-form tidy rows (dr_level, axis, field, value) for exact stats.
- series:  named time-series arrays (trajectories, training curves) for plots.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class SummaryRecord:
    """One scalar observation. axis=None marks a run-level scalar (e.g. survival_pct)."""
    dr_level: str
    axis: Optional[str]
    field: str
    value: float


@dataclass
class IngestResult:
    """Normalized output of any adapter. All three members default to empty."""
    summary: list = dc_field(default_factory=list)        # list[SummaryRecord]
    series: dict = dc_field(default_factory=dict)          # dict[str, np.ndarray]
    meta: dict = dc_field(default_factory=dict)            # source path, format, run_id, ...


class IngestAdapter(ABC):
    """Source -> IngestResult. Subclasses implement can_handle + ingest."""

    @abstractmethod
    def can_handle(self, path: Path) -> bool:
        """Cheap check (extension / sentinel filename) — no full parse."""

    @abstractmethod
    def ingest(self, path: Path) -> IngestResult:
        """Parse `path` into a normalized IngestResult. Loud-fail on malformed input."""
```

Create `omx-core/omx_core/ingest/__init__.py`:

```python
"""omx_core.ingest — source adapters normalizing to IngestResult."""
from omx_core.ingest.base import IngestResult, SummaryRecord, IngestAdapter

__all__ = ["IngestResult", "SummaryRecord", "IngestAdapter"]
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd omx-core && python3 -m pytest tests/test_ingest_base.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add omx-core/omx_core/ingest/__init__.py omx-core/omx_core/ingest/base.py omx-core/tests/test_ingest_base.py
git commit -m "feat(ingest): IngestResult/SummaryRecord containers + IngestAdapter ABC

One normalized container (long-form summary rows + named series arrays) so the
reduce layer never learns a source format (build-order #1)."
```

---

### Task 4: `EvalSummaryAdapter` (nested eval_dr `summary.json`) + fixtures

**Files:**
- Create: `omx-core/omx_core/ingest/eval_summary.py`
- Create: `omx-core/tests/fixtures/summary.json`
- Create: `omx-core/tests/conftest.py` (fixtures dir resolver)
- Test: `omx-core/tests/test_ingest_eval_summary.py`

- [ ] **Step 1: Create the shrunk fixture (real schema, 2 levels, 2 axes + att_norm + survival_pct)**

Create `omx-core/tests/fixtures/summary.json`:

```json
{
  "none": {
    "roll": {
      "os_env_mean": 11.18, "os_env_std": 0.85, "os_env_median": 11.14, "os_env_q90": 12.06,
      "us_env_mean": 8.38, "us_env_std": 9.75,
      "n_gt20": 1.33, "n_gt40": 0.0, "n_us_lt_minus20": 0.66,
      "rise_time": 0.80, "rise_time_std": 0.28,
      "ss_error": 0.76, "ss_error_std": 0.48, "ss_jitter": 0.43, "ss_jitter_std": 0.26
    },
    "pitch": {
      "os_env_mean": 8.72, "os_env_std": 0.70, "os_env_median": 8.44, "os_env_q90": 9.49,
      "us_env_mean": 0.0, "us_env_std": 0.0,
      "n_gt20": 0.0, "n_gt40": 0.0, "n_us_lt_minus20": 0.0,
      "rise_time": 0.30, "rise_time_std": 0.002,
      "ss_error": 0.21, "ss_error_std": 0.13, "ss_jitter": 0.17, "ss_jitter_std": 0.17
    },
    "att_norm": {
      "ss_error": 0.83, "ss_error_std": 0.52, "ss_jitter": 0.41, "ss_jitter_std": 0.25
    },
    "survival_pct": 100.0
  },
  "hard": {
    "roll": {
      "os_env_mean": 15.93, "os_env_std": 11.68, "os_env_median": 12.13, "os_env_q90": 29.18,
      "us_env_mean": 0.0, "us_env_std": 0.0,
      "n_gt20": 1.0, "n_gt40": 0.33, "n_us_lt_minus20": 0.0,
      "rise_time": 0.65, "rise_time_std": 0.23,
      "ss_error": 0.23, "ss_error_std": 0.13, "ss_jitter": 0.11, "ss_jitter_std": 0.07
    },
    "pitch": {
      "os_env_mean": 8.21, "os_env_std": 2.43, "os_env_median": 7.93, "os_env_q90": 10.73,
      "us_env_mean": 0.07, "us_env_std": 0.11,
      "n_gt20": 0.0, "n_gt40": 0.0, "n_us_lt_minus20": 0.0,
      "rise_time": 0.32, "rise_time_std": 0.03,
      "ss_error": 0.14, "ss_error_std": 0.09, "ss_jitter": 0.02, "ss_jitter_std": 0.01
    },
    "att_norm": {
      "ss_error": 0.30, "ss_error_std": 0.13, "ss_jitter": 0.10, "ss_jitter_std": 0.07
    },
    "survival_pct": 100.0
  }
}
```

- [ ] **Step 2: Create the conftest fixtures resolver**

Create `omx-core/tests/conftest.py`:

```python
from pathlib import Path
import pytest


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent / "fixtures"
```

- [ ] **Step 3: Write the failing test**

Create `omx-core/tests/test_ingest_eval_summary.py`:

```python
from omx_core.ingest import IngestResult, SummaryRecord
from omx_core.ingest.eval_summary import EvalSummaryAdapter


def test_can_handle_summary_json(fixtures_dir):
    a = EvalSummaryAdapter()
    assert a.can_handle(fixtures_dir / "summary.json") is True
    assert a.can_handle(fixtures_dir / "data_none.npz") is False


def test_ingest_returns_ingest_result(fixtures_dir):
    res = EvalSummaryAdapter().ingest(fixtures_dir / "summary.json")
    assert isinstance(res, IngestResult)
    assert res.series == {}                      # eval-summary is tabular only
    assert res.meta["format"] == "eval_summary"


def test_record_count_matches_schema(fixtures_dir):
    # 2 levels x (2 full axes x 15 fields + att_norm x 4 fields + survival_pct x 1)
    # per level = 30 + 4 + 1 = 35 ; total = 70
    res = EvalSummaryAdapter().ingest(fixtures_dir / "summary.json")
    assert len(res.summary) == 70


def test_axis_field_extracted_exactly(fixtures_dir):
    res = EvalSummaryAdapter().ingest(fixtures_dir / "summary.json")
    rec = [r for r in res.summary
           if r.dr_level == "none" and r.axis == "roll" and r.field == "ss_error"]
    assert len(rec) == 1
    assert rec[0].value == 0.76


def test_att_norm_asymmetry_handled(fixtures_dir):
    # att_norm must yield exactly its 4 present fields, not 15
    res = EvalSummaryAdapter().ingest(fixtures_dir / "summary.json")
    att = [r for r in res.summary if r.dr_level == "none" and r.axis == "att_norm"]
    assert {r.field for r in att} == {"ss_error", "ss_error_std", "ss_jitter", "ss_jitter_std"}


def test_survival_pct_is_run_level_scalar(fixtures_dir):
    res = EvalSummaryAdapter().ingest(fixtures_dir / "summary.json")
    surv = [r for r in res.summary if r.field == "survival_pct"]
    assert len(surv) == 2                          # one per level
    assert all(r.axis is None for r in surv)
    assert all(r.value == 100.0 for r in surv)


def test_malformed_json_raises(tmp_path):
    bad = tmp_path / "summary.json"
    bad.write_text("{not valid json")
    import pytest
    with pytest.raises(Exception):
        EvalSummaryAdapter().ingest(bad)
```

- [ ] **Step 4: Run to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_ingest_eval_summary.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.ingest.eval_summary'`.

- [ ] **Step 5: Write the implementation**

Create `omx-core/omx_core/ingest/eval_summary.py`:

```python
"""omx_core.ingest.eval_summary — eval_dr summary.json adapter.

Schema (verified): {dr_level: {axis: {field: float}}} where one member of each
level (survival_pct) is a bare float, not a dict, and att_norm carries a subset
of fields. Flattened to long-form SummaryRecords; survival_pct -> axis=None.
"""
import json
from pathlib import Path

from omx_core.ingest.base import IngestAdapter, IngestResult, SummaryRecord


class EvalSummaryAdapter(IngestAdapter):
    def can_handle(self, path: Path) -> bool:
        return Path(path).name == "summary.json"

    def ingest(self, path: Path) -> IngestResult:
        path = Path(path)
        data = json.loads(path.read_text())  # loud-fail on malformed JSON
        records = []
        for dr_level, level_body in data.items():
            for key, member in level_body.items():
                if isinstance(member, dict):          # an axis dict (roll, ..., att_norm)
                    for field_name, value in member.items():
                        records.append(SummaryRecord(dr_level, key, field_name, float(value)))
                else:                                 # a run-level scalar (survival_pct)
                    records.append(SummaryRecord(dr_level, None, key, float(member)))
        return IngestResult(
            summary=records,
            series={},
            meta={"source": str(path), "format": "eval_summary"},
        )
```

- [ ] **Step 6: Run to verify it passes**

Run: `cd omx-core && python3 -m pytest tests/test_ingest_eval_summary.py -v`
Expected: PASS (7 passed).

- [ ] **Step 7: Commit**

```bash
git add omx-core/omx_core/ingest/eval_summary.py omx-core/tests/fixtures/summary.json omx-core/tests/conftest.py omx-core/tests/test_ingest_eval_summary.py
git commit -m "feat(ingest): EvalSummaryAdapter for eval_dr summary.json

Flattens {dr_level: {axis: {field}}} to long-form SummaryRecords; tolerates
att_norm field-subset and survival_pct run-level scalar (axis=None). Fixtures
mirror real eval_dr schema (build-order #1)."
```

---

### Task 5: `LongFormCsvAdapter` (flat CSV → SummaryRecords)

**Files:**
- Create: `omx-core/omx_core/ingest/csv_longform.py`
- Create: `omx-core/tests/fixtures/metrics_long.csv`
- Test: `omx-core/tests/test_ingest_csv_longform.py`

- [ ] **Step 1: Create the fixture**

Create `omx-core/tests/fixtures/metrics_long.csv`:

```csv
dr_level,axis,field,value
none,roll,ss_error,0.76
none,roll,ss_error_std,0.48
none,,survival_pct,100.0
hard,pitch,ss_error,0.14
```

(Note: the blank `axis` cell on the survival_pct row encodes a run-level scalar — `axis=None`.)

- [ ] **Step 2: Write the failing test**

Create `omx-core/tests/test_ingest_csv_longform.py`:

```python
import pytest
from omx_core.ingest import IngestResult, SummaryRecord
from omx_core.ingest.csv_longform import LongFormCsvAdapter


def test_can_handle_csv(fixtures_dir):
    a = LongFormCsvAdapter()
    assert a.can_handle(fixtures_dir / "metrics_long.csv") is True
    assert a.can_handle(fixtures_dir / "summary.json") is False


def test_ingest_row_count(fixtures_dir):
    res = LongFormCsvAdapter().ingest(fixtures_dir / "metrics_long.csv")
    assert isinstance(res, IngestResult)
    assert len(res.summary) == 4
    assert res.meta["format"] == "csv_longform"


def test_blank_axis_becomes_none(fixtures_dir):
    res = LongFormCsvAdapter().ingest(fixtures_dir / "metrics_long.csv")
    surv = [r for r in res.summary if r.field == "survival_pct"]
    assert len(surv) == 1
    assert surv[0].axis is None
    assert surv[0].value == 100.0


def test_value_is_float(fixtures_dir):
    res = LongFormCsvAdapter().ingest(fixtures_dir / "metrics_long.csv")
    r = [x for x in res.summary if x.dr_level == "none" and x.axis == "roll"
         and x.field == "ss_error"][0]
    assert r.value == 0.76
    assert isinstance(r.value, float)


def test_missing_required_column_raises(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("dr_level,axis,value\nnone,roll,0.1\n")  # no 'field' column
    with pytest.raises(ValueError):
        LongFormCsvAdapter().ingest(bad)
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_ingest_csv_longform.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.ingest.csv_longform'`.

- [ ] **Step 4: Write the implementation**

Create `omx-core/omx_core/ingest/csv_longform.py`:

```python
"""omx_core.ingest.csv_longform — flat long-form CSV adapter.

Expects columns: dr_level, axis, field, value. A blank axis cell -> axis=None
(run-level scalar). Proves the IngestAdapter abstraction across a second,
genuinely different input format (parsing) with the same SummaryRecord output.
"""
import csv
from pathlib import Path

from omx_core.ingest.base import IngestAdapter, IngestResult, SummaryRecord

_REQUIRED = {"dr_level", "axis", "field", "value"}


class LongFormCsvAdapter(IngestAdapter):
    def can_handle(self, path: Path) -> bool:
        return Path(path).suffix == ".csv"

    def ingest(self, path: Path) -> IngestResult:
        path = Path(path)
        with path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            header = set(reader.fieldnames or [])
            missing = _REQUIRED - header
            if missing:
                raise ValueError(f"CSV {path} missing required columns: {sorted(missing)}")
            records = []
            for row in reader:
                axis = row["axis"] if row["axis"] else None
                records.append(
                    SummaryRecord(row["dr_level"], axis, row["field"], float(row["value"]))
                )
        return IngestResult(
            summary=records, series={},
            meta={"source": str(path), "format": "csv_longform"},
        )
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd omx-core && python3 -m pytest tests/test_ingest_csv_longform.py -v`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add omx-core/omx_core/ingest/csv_longform.py omx-core/tests/fixtures/metrics_long.csv omx-core/tests/test_ingest_csv_longform.py
git commit -m "feat(ingest): LongFormCsvAdapter (flat dr_level,axis,field,value CSV)

Second concrete adapter proving the ABC across a different input format; blank
axis -> None, missing required column loud-fails (build-order #1)."
```

---

### Task 6: WandB / TensorBoard adapter stubs (deferred to #4)

**Files:**
- Create: `omx-core/omx_core/ingest/stubs.py`
- Test: `omx-core/tests/test_ingest_stubs.py`

- [ ] **Step 1: Write the failing test**

Create `omx-core/tests/test_ingest_stubs.py`:

```python
import pytest
from omx_core.ingest import IngestAdapter
from omx_core.ingest.stubs import WandbAdapter, TensorboardAdapter


def test_stubs_are_adapters():
    assert isinstance(WandbAdapter(), IngestAdapter)
    assert isinstance(TensorboardAdapter(), IngestAdapter)


def test_wandb_can_handle_by_scheme():
    assert WandbAdapter().can_handle("wandb://entity/project/run") is True
    assert WandbAdapter().can_handle("/local/summary.json") is False


def test_tb_can_handle_by_event_filename():
    assert TensorboardAdapter().can_handle("/x/events.out.tfevents.123") is True
    assert TensorboardAdapter().can_handle("/x/summary.json") is False


def test_ingest_raises_not_implemented_with_build_pointer():
    with pytest.raises(NotImplementedError, match="build #4"):
        WandbAdapter().ingest("wandb://e/p/r")
    with pytest.raises(NotImplementedError, match="build #4"):
        TensorboardAdapter().ingest("/x/events.out.tfevents.1")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_ingest_stubs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.ingest.stubs'`.

- [ ] **Step 3: Write the implementation**

Create `omx-core/omx_core/ingest/stubs.py`:

```python
"""omx_core.ingest.stubs — interface signposts for WandB / TensorBoard.

These declare the extension points (so the ABC has named network-source members)
but defer real ingestion to build #4 (exp-analyze), where they are validated on
live data. can_handle is implemented (cheap, no network); ingest loud-fails with
a build pointer rather than silently returning empty.
"""
from pathlib import Path

from omx_core.ingest.base import IngestAdapter, IngestResult


class WandbAdapter(IngestAdapter):
    def can_handle(self, path) -> bool:
        return str(path).startswith("wandb://")

    def ingest(self, path) -> IngestResult:
        raise NotImplementedError(
            "WandbAdapter.ingest is a deferred extension point — implemented in "
            "build #4 (exp-analyze) where WandB is validated on live data."
        )


class TensorboardAdapter(IngestAdapter):
    def can_handle(self, path) -> bool:
        return "events.out.tfevents" in Path(path).name

    def ingest(self, path) -> IngestResult:
        raise NotImplementedError(
            "TensorboardAdapter.ingest is a deferred extension point — implemented "
            "in build #4 (exp-analyze) where TB event files are validated."
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd omx-core && python3 -m pytest tests/test_ingest_stubs.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add omx-core/omx_core/ingest/stubs.py omx-core/tests/test_ingest_stubs.py
git commit -m "feat(ingest): WandB/TB adapter stubs (extension points, defer to #4)

can_handle implemented (cheap, no network); ingest loud-fails with a build #4
pointer instead of silently returning empty (build-order #1)."
```

---

### Task 7: `reduce.summarize` — long-form → DataFrame + CV = std/mean

**Files:**
- Create: `omx-core/omx_core/reduce/__init__.py`
- Create: `omx-core/omx_core/reduce/summarize.py`
- Test: `omx-core/tests/test_reduce_summarize.py`

- [ ] **Step 1: Write the failing test**

Create `omx-core/tests/test_reduce_summarize.py`:

```python
import math
import pandas as pd
from omx_core.ingest import SummaryRecord
from omx_core.reduce.summarize import to_dataframe, add_cv


def _recs():
    return [
        SummaryRecord("none", "roll", "ss_error", 0.76),
        SummaryRecord("none", "roll", "ss_error_std", 0.48),
        SummaryRecord("none", "pitch", "ss_error", 0.20),
        SummaryRecord("none", "pitch", "ss_error_std", 0.00),  # mean nonzero, std zero
        SummaryRecord("none", None, "survival_pct", 100.0),
    ]


def test_to_dataframe_columns():
    df = to_dataframe(_recs())
    assert list(df.columns) == ["dr_level", "axis", "field", "value"]
    assert len(df) == 5


def test_to_dataframe_keeps_none_axis():
    df = to_dataframe(_recs())
    surv = df[df.field == "survival_pct"]
    assert surv.iloc[0]["axis"] is None or pd.isna(surv.iloc[0]["axis"])


def test_add_cv_computes_std_over_mean():
    df = to_dataframe(_recs())
    cv = add_cv(df, base_field="ss_error")
    roll = cv[(cv.axis == "roll")].iloc[0]
    assert math.isclose(roll["cv"], 0.48 / 0.76, rel_tol=1e-9)
    pitch = cv[(cv.axis == "pitch")].iloc[0]
    assert pitch["cv"] == 0.0                       # std 0 over mean 0.20


def test_add_cv_zero_mean_is_nan():
    recs = [SummaryRecord("none", "vx", "ss_error", 0.0),
            SummaryRecord("none", "vx", "ss_error_std", 0.0)]
    cv = add_cv(to_dataframe(recs), base_field="ss_error")
    assert math.isnan(cv.iloc[0]["cv"])            # 0/0 -> nan, never raise


def test_add_cv_only_for_axes_with_both_fields():
    # att_norm-style: has ss_error + ss_error_std -> CV present
    recs = [SummaryRecord("hard", "att_norm", "ss_error", 0.30),
            SummaryRecord("hard", "att_norm", "ss_error_std", 0.13)]
    cv = add_cv(to_dataframe(recs), base_field="ss_error")
    assert len(cv) == 1
    assert math.isclose(cv.iloc[0]["cv"], 0.13 / 0.30, rel_tol=1e-9)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_reduce_summarize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.reduce'`.

- [ ] **Step 3: Write the implementation**

Create `omx-core/omx_core/reduce/summarize.py`:

```python
"""omx_core.reduce.summarize — long-form records -> exact aggregates.

The repo's mandatory rule (03-analysis-quality): CV = ss_error_std / ss_error,
computed per (dr_level, axis). Exact arithmetic via pandas, never LLM mental math.
"""
import numpy as np
import pandas as pd

from omx_core.ingest.base import SummaryRecord


def to_dataframe(records) -> pd.DataFrame:
    """list[SummaryRecord] -> tidy DataFrame [dr_level, axis, field, value]."""
    return pd.DataFrame(
        [(r.dr_level, r.axis, r.field, r.value) for r in records],
        columns=["dr_level", "axis", "field", "value"],
    )


def add_cv(df: pd.DataFrame, base_field: str, std_field: str = None) -> pd.DataFrame:
    """Per (dr_level, axis), CV = std/mean for base_field.

    Returns one row per (dr_level, axis) that has BOTH base_field and its std,
    with columns [dr_level, axis, mean, std, cv]. 0/0 -> nan (never raises).
    """
    std_field = std_field or f"{base_field}_std"
    base = df[df.field == base_field][["dr_level", "axis", "value"]].rename(
        columns={"value": "mean"})
    std = df[df.field == std_field][["dr_level", "axis", "value"]].rename(
        columns={"value": "std"})
    merged = base.merge(std, on=["dr_level", "axis"], how="inner")
    # 0/0 -> nan; x/0 -> inf (numpy default with divide guard)
    with np.errstate(divide="ignore", invalid="ignore"):
        merged["cv"] = merged["std"] / merged["mean"]
    return merged
```

Create `omx-core/omx_core/reduce/__init__.py`:

```python
"""omx_core.reduce — Claude-free reduction verbs (summarize / series / plot / cache)."""
from omx_core.reduce.summarize import to_dataframe, add_cv

__all__ = ["to_dataframe", "add_cv"]
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd omx-core && python3 -m pytest tests/test_reduce_summarize.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add omx-core/omx_core/reduce/__init__.py omx-core/omx_core/reduce/summarize.py omx-core/tests/test_reduce_summarize.py
git commit -m "feat(reduce): summarize — long-form DataFrame + CV=std/mean

Encodes the repo CV rule (03-analysis-quality) per (dr_level, axis); 0/0 -> nan,
never raises. Exact pandas arithmetic, no LLM math (build-order #1)."
```

---

### Task 8: `reduce.series` — npz loader + downsample

**Files:**
- Create: `omx-core/omx_core/reduce/series.py`
- Create: `omx-core/tests/fixtures/data_none.npz` (generated, Step 1)
- Test: `omx-core/tests/test_reduce_series.py`

- [ ] **Step 1: Generate the npz fixture (small, real array names/shapes)**

Run this one-off to create the fixture (commit the resulting `.npz`):

```bash
cd omx-core && python3 -c "
import numpy as np
from pathlib import Path
d = Path('tests/fixtures'); d.mkdir(parents=True, exist_ok=True)
n, e = 100, 4
np.savez(d / 'data_none.npz',
    time=np.linspace(0, 1, n),
    target_roll_deg=np.zeros(n),
    actual_roll_deg=np.random.RandomState(0).randn(n, e),
    error_roll=np.random.RandomState(1).randn(n, e),
    lin_vel_norm=np.abs(np.random.RandomState(2).randn(n, e)),
    terminated=np.zeros((n, e), dtype=bool),
    time_to_failure=np.full(e, np.nan),
)
print('wrote', d / 'data_none.npz')
"
```

Expected: `wrote tests/fixtures/data_none.npz`.

- [ ] **Step 2: Write the failing test**

Create `omx-core/tests/test_reduce_series.py`:

```python
import numpy as np
import pytest
from omx_core.reduce.series import load_npz, downsample


def test_load_npz_returns_named_arrays(fixtures_dir):
    arrays = load_npz(fixtures_dir / "data_none.npz")
    assert "time" in arrays and "actual_roll_deg" in arrays
    assert arrays["actual_roll_deg"].shape == (100, 4)
    assert arrays["time"].shape == (100,)


def test_downsample_caps_point_count():
    arr = np.arange(10000)
    out = downsample(arr, max_points=1000)
    assert out.shape[0] <= 1000
    assert out[0] == 0                       # keeps the first point


def test_downsample_2d_thins_axis0_only():
    arr = np.arange(2000 * 4).reshape(2000, 4)
    out = downsample(arr, max_points=500)
    assert out.shape[0] <= 500
    assert out.shape[1] == 4                  # columns (envs) untouched


def test_downsample_noop_when_already_small():
    arr = np.arange(50)
    out = downsample(arr, max_points=1000)
    assert np.array_equal(out, arr)           # no change


def test_downsample_rejects_nonpositive_max():
    with pytest.raises(ValueError):
        downsample(np.arange(10), max_points=0)
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_reduce_series.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.reduce.series'`.

- [ ] **Step 4: Write the implementation**

Create `omx-core/omx_core/reduce/series.py`:

```python
"""omx_core.reduce.series — time-series loading + downsampling for plots.

Trajectories are (timesteps, n_envs); downsample thins axis 0 (time) by a
stride so a PNG curve carries <= max_points without distorting shape. Design 5:
keep plots small; a few thousand points is plenty for a vision-read curve.
"""
import math

import numpy as np


def load_npz(path) -> dict:
    """Load a .npz into a plain {name: ndarray} dict (materialized, file closed)."""
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


def downsample(arr: np.ndarray, max_points: int = 2000) -> np.ndarray:
    """Stride-thin along axis 0 so len(axis0) <= max_points. Keeps the first row.

    1-D and N-D supported (only axis 0 is thinned). No-op if already small.
    """
    if max_points <= 0:
        raise ValueError(f"max_points must be positive, got {max_points}")
    n = arr.shape[0]
    if n <= max_points:
        return arr
    stride = math.ceil(n / max_points)
    return arr[::stride]
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd omx-core && python3 -m pytest tests/test_reduce_series.py -v`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add omx-core/omx_core/reduce/series.py omx-core/tests/fixtures/data_none.npz omx-core/tests/test_reduce_series.py
git commit -m "feat(reduce): series — npz loader + axis-0 stride downsample

Thins (timesteps, n_envs) trajectories to <= max_points for vision-read plots,
keeps first row, no-op when small (build-order #1)."
```

---

### Task 9: `reduce.plot` — headless Agg line/bar PNG

**Files:**
- Create: `omx-core/omx_core/reduce/plot.py`
- Test: `omx-core/tests/test_reduce_plot.py`

- [ ] **Step 1: Write the failing test**

Create `omx-core/tests/test_reduce_plot.py`:

```python
import numpy as np
from omx_core.reduce.plot import line_plot, bar_plot


def _is_png(path):
    return path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_line_plot_writes_valid_png(tmp_path):
    out = tmp_path / "curve.png"
    x = np.linspace(0, 1, 200)
    res = line_plot(x, {"roll": np.sin(x * 6.28), "pitch": np.cos(x * 6.28)},
                    out, title="attitude")
    assert res == out
    assert out.exists() and out.stat().st_size > 0
    assert _is_png(out)


def test_line_plot_caps_width_px(tmp_path):
    out = tmp_path / "wide.png"
    x = np.arange(50)
    line_plot(x, {"a": x}, out, max_px=1200)
    from PIL import Image  # matplotlib ships PIL; if absent, read IHDR manually
    try:
        w, _ = Image.open(out).size
        assert w <= 1200
    except ImportError:
        # fallback: PNG IHDR width is bytes 16-20 big-endian
        b = out.read_bytes()
        w = int.from_bytes(b[16:20], "big")
        assert w <= 1200


def test_bar_plot_writes_valid_png(tmp_path):
    out = tmp_path / "bars.png"
    res = bar_plot(["roll", "pitch", "yaw"], [0.76, 0.20, 0.001], out,
                   title="ss_error by axis")
    assert res == out
    assert _is_png(out)


def test_plot_creates_parent_dir(tmp_path):
    out = tmp_path / "nested" / "deep" / "curve.png"
    line_plot(np.arange(10), {"a": np.arange(10)}, out)
    assert out.exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_reduce_plot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.reduce.plot'`.

- [ ] **Step 3: Write the implementation**

Create `omx-core/omx_core/reduce/plot.py`:

```python
"""omx_core.reduce.plot — headless PNG generation (matplotlib Agg backend).

CRITICAL: set the Agg backend BEFORE importing pyplot — this container is
headless (no display). Design 5: cap width so a vision-read PNG stays small.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")          # MUST precede pyplot import (headless Docker)
import matplotlib.pyplot as plt   # noqa: E402

_DPI = 100


def _save(fig, out_path, max_px):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # cap figure width: width_in * dpi <= max_px
    max_in = max_px / _DPI
    w_in, h_in = fig.get_size_inches()
    if w_in > max_in:
        fig.set_size_inches(max_in, h_in * (max_in / w_in))
    fig.savefig(out_path, dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    return out_path


def line_plot(x, series: dict, out_path, *, title=None, max_px=2576) -> Path:
    """Overlay named 1-D series against x. series = {label: ndarray}."""
    fig, ax = plt.subplots()
    for label, y in series.items():
        ax.plot(x, y, label=label, linewidth=1.0)
    if title:
        ax.set_title(title)
    ax.legend(loc="best", fontsize="small")
    ax.grid(True, alpha=0.3)
    return _save(fig, out_path, max_px)


def bar_plot(labels, values, out_path, *, title=None, max_px=2576) -> Path:
    """Simple categorical bar chart (e.g. ss_error per axis)."""
    fig, ax = plt.subplots()
    ax.bar(range(len(labels)), values)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    if title:
        ax.set_title(title)
    ax.grid(True, axis="y", alpha=0.3)
    return _save(fig, out_path, max_px)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd omx-core && python3 -m pytest tests/test_reduce_plot.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add omx-core/omx_core/reduce/plot.py omx-core/tests/test_reduce_plot.py
git commit -m "feat(reduce): plot — headless Agg line/bar PNG with width cap

Agg backend set before pyplot import (headless Docker); caps width to design-5
ceiling; creates parent dirs (build-order #1)."
```

---

### Task 10: `reduce.cache` — npz derived-data cache via omx_paths

**Files:**
- Create: `omx-core/omx_core/reduce/cache.py`
- Test: `omx-core/tests/test_reduce_cache.py`

- [ ] **Step 1: Write the failing test**

Create `omx-core/tests/test_reduce_cache.py`:

```python
import numpy as np
from omx_core.omx_paths import OmxPaths
from omx_core.reduce.cache import write_cache, read_cache


def test_read_missing_returns_none(tmp_path):
    p = OmxPaths(tmp_path)
    assert read_cache(p, "run01", source="eval_summary", metric="ss_error") is None


def test_write_then_read_roundtrip(tmp_path):
    p = OmxPaths(tmp_path)
    arrays = {"x": np.arange(5), "y": np.ones((3, 2))}
    out = write_cache(p, "run01", source="eval_summary", metric="ss_error", arrays=arrays)
    assert out.suffix == ".npz"
    back = read_cache(p, "run01", source="eval_summary", metric="ss_error")
    assert set(back) == {"x", "y"}
    assert np.array_equal(back["x"], np.arange(5))
    assert back["y"].shape == (3, 2)


def test_write_is_atomic_no_tmp_left(tmp_path):
    p = OmxPaths(tmp_path)
    write_cache(p, "run01", source="eval_summary", metric="ss_error", arrays={"x": np.arange(3)})
    cache_dir = p.cache_path("run01", source="eval_summary", metric="ss_error").parent
    leftovers = [f.name for f in cache_dir.iterdir() if f.name.endswith(".tmp")]
    assert leftovers == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_reduce_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.reduce.cache'`.

- [ ] **Step 3: Write the implementation**

Create `omx-core/omx_core/reduce/cache.py`:

```python
"""omx_core.reduce.cache — re-derivable derived-data cache in .omx/runs/<id>/cache/.

Numpy .npz (pyarrow absent; design 10.2 'parquet' was an example, the principle
is a re-derivable cache). Path comes ONLY from omx_paths.cache_path; atomic via
atomic_path. read_cache returns None on miss (caller re-derives).
"""
import numpy as np

from omx_core.omx_paths import OmxPaths, atomic_path


def write_cache(paths: OmxPaths, run_id, *, source, metric, arrays: dict):
    """Atomically np.savez `arrays` to the canonical cache path. Returns the path."""
    target = paths.cache_path(run_id, source=source, metric=metric)
    target.parent.mkdir(parents=True, exist_ok=True)
    with atomic_path(target) as tmp:
        # np.savez appends .npz if absent; write to an explicit .npz tmp to avoid that
        np.savez(tmp, **arrays)
    return target


def read_cache(paths: OmxPaths, run_id, *, source, metric):
    """Return {name: ndarray} if the cache exists, else None (caller re-derives)."""
    target = paths.cache_path(run_id, source=source, metric=metric)
    if not target.exists():
        return None
    with np.load(target) as z:
        return {k: z[k] for k in z.files}
```

> Implementation note for the engineer: `np.savez(tmp, ...)` where `tmp` is a `Path` with a `.tmp` suffix will append `.npz`, producing `foo.tmp.npz` and breaking the atomic rename. Pass a file object instead so no suffix is appended: open `tmp` in binary and `np.savez(fh, **arrays)`. Update the implementation to:
> ```python
>     with atomic_path(target) as tmp:
>         with open(tmp, "wb") as fh:
>             np.savez(fh, **arrays)
> ```
> Verify the atomic test (`test_write_is_atomic_no_tmp_left`) and roundtrip both pass with this form.

- [ ] **Step 4: Run to verify it passes**

Run: `cd omx-core && python3 -m pytest tests/test_reduce_cache.py -v`
Expected: PASS (3 passed). If `test_write_then_read_roundtrip` fails because a `*.tmp.npz` appeared, apply the file-object form from the note above.

- [ ] **Step 5: Update reduce/__init__ exports**

In `omx-core/omx_core/reduce/__init__.py`, extend to:

```python
"""omx_core.reduce — Claude-free reduction verbs (summarize / series / plot / cache)."""
from omx_core.reduce.summarize import to_dataframe, add_cv
from omx_core.reduce.series import load_npz, downsample
from omx_core.reduce.plot import line_plot, bar_plot
from omx_core.reduce.cache import write_cache, read_cache

__all__ = [
    "to_dataframe", "add_cv",
    "load_npz", "downsample",
    "line_plot", "bar_plot",
    "write_cache", "read_cache",
]
```

- [ ] **Step 6: Run the full suite**

Run: `cd omx-core && python3 -m pytest tests/ -q`
Expected: PASS (all tests green).

- [ ] **Step 7: Commit**

```bash
git add omx-core/omx_core/reduce/cache.py omx-core/omx_core/reduce/__init__.py omx-core/tests/test_reduce_cache.py
git commit -m "feat(reduce): cache — atomic npz derived-data cache via omx_paths

Path only from cache_path (now .npz); atomic_path write; read returns None on
miss. Completes reduce __init__ exports (build-order #1)."
```

---

### Task 11: `omx` CLI — `ingest` / `reduce summarize` verbs

**Files:**
- Create: `omx-core/omx_core/cli.py`
- Modify: `omx-core/pyproject.toml` (add `[project.scripts]`)
- Test: `omx-core/tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Create `omx-core/tests/test_cli.py`:

```python
import json
from omx_core.cli import main


def test_ingest_eval_summary_prints_counts(fixtures_dir, capsys):
    rc = main(["ingest", "--path", str(fixtures_dir / "summary.json"),
               "--format", "eval_summary"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["format"] == "eval_summary"
    assert out["n_summary"] == 70
    assert out["n_series"] == 0


def test_ingest_csv(fixtures_dir, capsys):
    rc = main(["ingest", "--path", str(fixtures_dir / "metrics_long.csv"),
               "--format", "csv_longform"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["n_summary"] == 4


def test_ingest_unknown_format_errors(fixtures_dir, capsys):
    rc = main(["ingest", "--path", str(fixtures_dir / "summary.json"),
               "--format", "nope"])
    assert rc != 0


def test_reduce_summarize_cv(fixtures_dir, capsys):
    rc = main(["reduce", "summarize", "--path", str(fixtures_dir / "summary.json"),
               "--format", "eval_summary", "--cv-field", "ss_error"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    # CV rows for axes that have both ss_error and ss_error_std
    rows = {(r["dr_level"], r["axis"]): r["cv"] for r in out["cv"]}
    assert ("none", "roll") in rows
    assert abs(rows[("none", "roll")] - 0.48 / 0.76) < 1e-6


def test_session_id_precedence_flag_wins(monkeypatch, capsys):
    monkeypatch.setenv("OMX_SESSION_ID", "from-env")
    rc = main(["session-id", "--session-id", "from-flag"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "from-flag"


def test_session_id_env_fallback(monkeypatch, capsys):
    monkeypatch.setenv("OMX_SESSION_ID", "from-env")
    rc = main(["session-id"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "from-env"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.cli'`.

- [ ] **Step 3: Write the implementation**

Create `omx-core/omx_core/cli.py`:

```python
"""omx_core.cli — the `omx` command (Claude-free verbs: ingest, reduce, session-id).

These verbs are pure Python so they are unit-testable from Bash with no Claude
or Isaac dependency. Skills (builds #3-#6) shell out to these.
"""
import argparse
import json
import os
import sys

from omx_core.ingest.eval_summary import EvalSummaryAdapter
from omx_core.ingest.csv_longform import LongFormCsvAdapter
from omx_core.omx_paths import resolve_session_id
from omx_core.reduce.summarize import to_dataframe, add_cv

_ADAPTERS = {
    "eval_summary": EvalSummaryAdapter,
    "csv_longform": LongFormCsvAdapter,
}


def _ingest(path, fmt):
    if fmt not in _ADAPTERS:
        raise SystemExit(f"unknown --format {fmt!r}; choose from {sorted(_ADAPTERS)}")
    return _ADAPTERS[fmt]().ingest(path)


def _cmd_ingest(args) -> int:
    res = _ingest(args.path, args.format)
    print(json.dumps({
        "format": res.meta.get("format"),
        "source": res.meta.get("source"),
        "n_summary": len(res.summary),
        "n_series": len(res.series),
    }))
    return 0


def _cmd_reduce_summarize(args) -> int:
    res = _ingest(args.path, args.format)
    df = to_dataframe(res.summary)
    cv = add_cv(df, base_field=args.cv_field)
    rows = [
        {"dr_level": r.dr_level, "axis": r.axis,
         "mean": r["mean"], "std": r["std"], "cv": r["cv"]}
        for _, r in cv.iterrows()
    ]
    print(json.dumps({"cv_field": args.cv_field, "cv": rows}))
    return 0


def _cmd_session_id(args) -> int:
    sid = resolve_session_id(
        explicit=args.session_id,
        env=os.environ.get("OMX_SESSION_ID"),
        autogen=f"{_now_stamp()}-{os.getpid()}",
    )
    print(sid)
    return 0


def _now_stamp() -> str:
    # local wall-clock; deterministic format YYYYMMDD-HHMMSS
    import time
    return time.strftime("%Y%m%d-%H%M%S", time.localtime())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="omx", description="OMX experiment-analysis core")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="normalize a source to IngestResult (prints counts)")
    pi.add_argument("--path", required=True)
    pi.add_argument("--format", required=True)
    pi.set_defaults(func=_cmd_ingest)

    pr = sub.add_parser("reduce", help="reduction verbs")
    rsub = pr.add_subparsers(dest="reduce_cmd", required=True)
    prs = rsub.add_parser("summarize", help="long-form -> CV table")
    prs.add_argument("--path", required=True)
    prs.add_argument("--format", required=True)
    prs.add_argument("--cv-field", default="ss_error", dest="cv_field")
    prs.set_defaults(func=_cmd_reduce_summarize)

    ps = sub.add_parser("session-id", help="resolve session id (flag>env>autogen)")
    ps.add_argument("--session-id", default=None, dest="session_id")
    ps.set_defaults(func=_cmd_session_id)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SystemExit as e:
        # argparse-style errors already printed; map non-int codes to 2
        return e.code if isinstance(e.code, int) else 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Add the console-script entry point**

In `omx-core/pyproject.toml`, add (or extend) a `[project.scripts]` table:

```toml
[project.scripts]
omx = "omx_core.cli:main"
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd omx-core && python3 -m pytest tests/test_cli.py -v`
Expected: PASS (6 passed).

> Note: `test_ingest_unknown_format_errors` expects a non-zero return. `_ingest` raises `SystemExit` with a string message; `main` maps a non-int code to `2`. Confirm the test sees `rc != 0` (it will be 2).

- [ ] **Step 6: Reinstall editable to register the console script + smoke-test the binary**

Run:
```bash
cd omx-core && pip install -e . --break-system-packages -q && omx ingest --path tests/fixtures/summary.json --format eval_summary
```
Expected: prints `{"format": "eval_summary", "source": ".../summary.json", "n_summary": 70, "n_series": 0}` and exits 0.

- [ ] **Step 7: Run the full suite**

Run: `cd omx-core && python3 -m pytest tests/ -q`
Expected: PASS (all green — #0's 110 + Task 1's 1 + all #1 tests).

- [ ] **Step 8: Commit**

```bash
git add omx-core/omx_core/cli.py omx-core/pyproject.toml omx-core/tests/test_cli.py
git commit -m "feat(cli): omx ingest / reduce summarize / session-id verbs

Claude-free CLI over the core; session-id honors flag>env>autogen (B2);
registers omx console script (build-order #1)."
```

---

## Self-Review

**1. Spec coverage (design §8 #1 = 'ingest adapters + reduce (summary-stat/downsample/plot) + .omx state schema, all paths via #0, Claude-free {ingest,reduce}'):**
- ingest adapters → Tasks 3 (ABC), 4 (eval-summary), 5 (csv), 6 (wandb/tb stubs). ✓
- reduce: summary-stat → Task 7; downsample → Task 8; plot → Task 9; cache → Task 10. ✓
- `.omx/` state schema → Task 2 (state.json) + Task 10 (cache, the run-bound derived-data schema). ✓
- all paths via #0 → Tasks 2/10 use `omx_paths` getters only; Task 1 fixes the one #0 mismatch (parquet→npz). ✓
- Claude-free + CLI-testable → Task 11 CLI; every test runs without Claude/Isaac/network. ✓
- WandB/TB validation deferred to #4 → Task 6 stubs loud-fail with a #4 pointer (honors the design DAG). ✓
- Evaluator runner NOT in scope → correctly absent (that's #2). ✓
- Permanent-tree writers NOT in scope → correctly absent (that's #4). ✓

**2. Placeholder scan:** No "TBD/TODO/implement later"; every code step shows complete code; every test shows full assertions; the one subtlety (np.savez suffix) is spelled out with the exact fix, not "handle edge cases". ✓

**3. Type consistency:** `IngestResult(summary:list, series:dict, meta:dict)` and `SummaryRecord(dr_level, axis, field, value)` defined in Task 3 are used identically in Tasks 4/5/6/7/11. `add_cv(df, base_field, std_field=None)` returns columns `[dr_level, axis, mean, std, cv]` — consumed with those exact names in Task 11's `_cmd_reduce_summarize`. `cache_path(..., source=, metric=)` keyword-only form (from #0) matched in Task 10. `resolve_session_id(explicit=, env=, autogen=)` signature (from #0) matched in Task 11. `atomic_path(target)` context-manager form matched in Tasks 2/10. ✓

**Known deferrals (intentional, tracked):** generic JSON adapter dropped (would equal eval-summary, YAGNI); parquet dropped (pyarrow absent); state.json carries only design-named keys (loop fills the rest in #6); `_now_stamp` uses `time.localtime` (the CLI is a real process, not a workflow script — `Date.now()` restriction is workflow-only). H4 root auto-discovery still owned by exp-init (#3), not added here.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-30-omx-core-skeleton.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec then quality) between tasks, continuous execution. Same pattern that took #0 to MERGE-READY.
2. **Inline Execution** — execute in this session with checkpoints.

Recommended: Subagent-Driven on a fresh `feat/omx-core-skeleton` branch (main = verified original). 11 tasks; natural review point after Task 6 if a blocker appears.
