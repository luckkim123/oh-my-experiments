# OMX build #4 — exp-analyze (PNG-vision hybrid analysis + WandB/TB adapters) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `exp-analyze` skill (Claude-required, PNG-vision hybrid router) plus the Claude-free core it orchestrates — real WandB/TensorBoard ingest adapters, a `metrics.yaml`→`Profile` loader, a candidate-plot generator, and a B3 plot-promotion verb — so a researcher can analyze N existing runs into an evidence-tagged `report.md` in the permanent output tree.

**Architecture:** Two layers per design §4. (1) Claude-free Python core, unit-tested via the `omx` CLI: WandB/TB adapters fill `IngestResult.series` (offline `.wandb` datastore parse + TB EventAccumulator), a `Profile` loader activates the B1 vocabulary tier, `omx plot` renders candidate PNGs into `scratch/<sid>/plots/`, `omx promote-plots` atomically moves report-referenced PNGs into the permanent `analysis/<aid>/plots/`. (2) The `exp-analyze` SKILL.md is a thin Claude wrapper that runs the §5 hybrid router (summary-stat-first → PNG-vision for shape → code-exec for exact numbers), writes `report.md` + `manifest.json`, and calls the core for every file IO. No `omx analyze` verb exists — analysis judgment is Claude's, file IO/validation is the core's (D8).

**Tech Stack:** Python 3.12 (stdlib + numpy/pandas/matplotlib/pyyaml already in core; wandb 0.25.0 + tensorboard as optional extras, deferred-imported inside adapters), pytest 9.x. WandB source = **local offline logs only** (`run-*.wandb` via `wandb.sdk.internal.datastore`, network/auth-free — user decision 2026-05-30). The skill is Claude-orchestrated; the core is Claude-free.

---

## Ground-truth (verified this session — do not re-derive)

- **eval_dr `summary.json`** = `{dr_level: {axis: {field: float}}}`; `survival_pct` is a bare float (axis=None). Already handled by `EvalSummaryAdapter` → long-form `IngestResult.summary`. Untouched here.
- **TB event file** (`events.out.tfevents.*`) = 139 scalar tags shaped `category/name` (e.g. `Reward/lin_vel`, `Track/att/roll_err_deg`), each a `(step, value)` series of ~5000 points. Parsed via `tensorboard.backend.event_processing.event_accumulator.EventAccumulator`.
- **WandB offline log** (`wandb/run-<id>/run-<id>.wandb`, wandb 0.25.0) = a datastore transaction log. `wandb.sdk.internal.datastore.DataStore().scan_data()` yields raw bytes → `wandb.proto.wandb_internal_pb2.Record`; `record_type=="history"` records carry `history.item[]` where the metric name = `item.key or "/".join(item.nested_key)` and the value = `item.value_json`. Verified: 1132 records, 201 history rows, keys like `Reward/total`, `Track/att/roll_err_deg`. **No network, no wandb-summary.json needed.**
- **`data_*.npz` trajectory** = named arrays: `time (T,)`, `target_<x>_deg (T,)`, `actual_<x>_deg (T,n_envs)`, `error_<x> (T,n_envs)`, `lin_vel_norm (T,n_envs)`, `terminated (T,n_envs) bool`, `time_to_failure (n_envs,)`. Loaded by existing `reduce.series.load_npz`. Untouched here.
- **`pyarrow` absent** → cache extension is `.npz` (already locked in `omx_paths.cache_path`).
- Core deps that are present: `wandb==0.25.0`, `tensorboard` (no `tensorflow`, no `tbparse`). Adapters MUST use `event_accumulator` (pure-TB, no TF) and `datastore` (no `wandb.Api`).

## Existing core surface this plan builds on (signatures — do NOT change them)

- `omx_core.ingest.base`: `IngestResult(summary:list, series:dict, meta:dict)`, `SummaryRecord(dr_level, axis, field, value)`, `IngestAdapter` ABC (`can_handle`, `ingest`).
- `omx_core.ingest.stubs`: `WandbAdapter` / `TensorboardAdapter` (currently `can_handle` real, `ingest` raises `NotImplementedError("...build #4...")`). **This plan replaces those stubs** — move them to real modules and delete `stubs.py` only after the new tests pass.
- `omx_core.reduce.series`: `load_npz(path)->dict`, `downsample(arr, max_points=2000)->ndarray`.
- `omx_core.reduce.plot`: `line_plot(x, series_dict, out_path, *, title=None, max_px=2576)->Path`, `bar_plot(labels, values, out_path, *, title=None, max_px=2576)->Path`.
- `omx_core.reduce.summarize`: `to_dataframe(records)->DataFrame`, `add_cv(df, base_field, std_field=None)->DataFrame`.
- `omx_core.omx_paths`: `OmxPaths(root, profile=None)` with getters `scratch_plots(session_id=)`, `analysis_dir/report_md/manifest_json/analysis_plot(metric,view)/analysis_table(metric,agg)/proposal_md`, `Profile(metrics,views,aggs,sources,run_id_regex)`, `atomic_path(target)` ctx mgr, `atomic_dir(target)` ctx mgr, `resolve_session_id(explicit,env,autogen)`, `OmxError`/`OmxPathError`.
- `omx_core.profile`: `default_metrics()->dict`, `validate_metrics_schema(data)->dict`, `bootstrap_profile(...)`. **This plan adds** `load_profile(...)` here.
- `omx_core.cli`: `build_parser()` adds subparsers; `main(argv)` maps non-int `SystemExit` → rc 2 on stderr. **This plan adds** `plot` and `promote-plots` subparsers.

## Constraints (design — non-negotiable)

- **No training/eval auto-launch.** exp-analyze reads *existing* run results only. The skill never shells `launch.sh` or any eval command.
- **Claude-free boundary.** Adapters, Profile loader, plot generation, promotion = pure Python in the core (unit-tested, no Claude). PNG-vision judgment + evidence tagging + report prose = the skill (Claude). The line never blurs: exact arithmetic & plot-file IO = core; "what does this curve show" = Claude.
- **B3 plot promotion.** Candidate PNGs land in `scratch/<sid>/plots/` first; ONLY those referenced in `report.md` are promoted (atomic `os.replace`) to permanent `analysis/<aid>/plots/`. Unreferenced stay in scratch for `omx clean`.
- **Public repo hygiene.** No absolute paths, no private repo names in code/skill — placeholders only. Tests use `tmp_path` + committed fixtures.
- **Path SSOT.** Every `.omx/` or output path comes from `omx_paths` getters. No string-concatenation of paths in new code.
- **Loud-fail.** Malformed adapter input, unknown metric token, missing referenced plot → raise `OmxError`/subclass, never silent-empty.
- Commit after each task; commit message ends with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Do not push (user-gated).

## File structure (created / modified)

- Create `omx-core/omx_core/ingest/tensorboard.py` — `TensorboardAdapter` (real). Fills `IngestResult.series` from TB scalars.
- Create `omx-core/omx_core/ingest/wandb_offline.py` — `WandbAdapter` (real, offline datastore). Fills `IngestResult.series` from `.wandb` history.
- Delete `omx-core/omx_core/ingest/stubs.py` (after Task 2 + 3 green) — re-export the two real classes from `ingest/__init__.py` for back-compat of `from omx_core.ingest.stubs import ...`? No — update the one test importer instead (Task 1 notes).
- Modify `omx-core/omx_core/profile.py` — add `load_profile(paths_or_root)->Profile` (reads `.omx/profile/metrics.yaml`, builds `omx_paths.Profile`).
- Create `omx-core/omx_core/reduce/promote.py` — `promote_plots(scratch_plots_dir, dest_plots_dir, referenced)->list[Path]` (B3 atomic promotion).
- Modify `omx-core/omx_core/reduce/__init__.py` — export `promote_plots`.
- Modify `omx-core/omx_core/cli.py` — add `omx plot` (series source → candidate PNG in scratch) + `omx promote-plots` verbs; register the two real adapters in `_ADAPTERS` so `omx ingest --format {wandb,tensorboard}` works.
- Modify `omx-core/pyproject.toml` — add `[project.optional-dependencies]` `analyze = ["wandb>=0.18", "tensorboard>=2.14"]`.
- Create `omx-core/tests/test_ingest_tensorboard.py`, `test_ingest_wandb_offline.py`, `test_profile_load.py`, `test_reduce_promote.py`, `test_cli_plot.py`, `test_cli_promote.py`.
- Create fixtures: a tiny synthetic TB event file + a tiny synthetic `.wandb` log, generated by a committed `tests/fixtures/_gen_analyze_fixtures.py` helper (run once, products committed). Rationale: real run files are 14–79 MB and live in a private repo — synthetic fixtures keep tests fast, deterministic, public-safe.
- Create `skills/exp-analyze/SKILL.md` — the Claude skill (hybrid router, report.md, plot promotion call, manifest).
- Modify `.claude-plugin/plugin.json` — append `"./skills/exp-analyze/"` to `skills`.
- Modify `docs/HANDOFF.md` — mark build #4 done.

---

## Task 1: Fixture generator + TB adapter test scaffold (failing test first)

**Files:**
- Create: `omx-core/tests/fixtures/_gen_analyze_fixtures.py`
- Create: `omx-core/tests/fixtures/tb/events.out.tfevents.synthetic` (generated)
- Create: `omx-core/tests/test_ingest_tensorboard.py`

- [ ] **Step 1: Write the fixture generator**

The generator writes a minimal but REAL TB event file (so the adapter is tested against the actual format, not a mock). Uses `tensorboard.summary.Event`/`SummaryWriter` via `torch`? No torch dependency — use TB's own writer.

```python
# omx-core/tests/fixtures/_gen_analyze_fixtures.py
"""Generate tiny, REAL TB + wandb fixtures for the analyze-adapter tests.

Run once; products are committed. Kept deterministic (fixed values, no RNG) so
the fixtures are reproducible and the adapter tests are exact.

    python3 tests/fixtures/_gen_analyze_fixtures.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent


def gen_tb():
    """Write a real TB event file with 2 scalar tags x 5 steps."""
    from tensorboard.summary import Writer  # tensorboard>=2.14 functional writer
    out_dir = HERE / "tb"
    out_dir.mkdir(parents=True, exist_ok=True)
    w = Writer(str(out_dir))
    for step in range(5):
        w.add_scalar("Reward/total", -0.5 + 0.1 * step, step)
        w.add_scalar("Track/att/roll_err_deg", 20.0 - 2.0 * step, step)
    w.flush()
    w.close()
    # TB names the file events.out.tfevents.<time>.<host>...; rename to a stable name
    produced = sorted(out_dir.glob("events.out.tfevents.*"))
    assert produced, "TB writer produced no event file"
    stable = out_dir / "events.out.tfevents.synthetic"
    if stable.exists():
        stable.unlink()
    produced[0].rename(stable)
    for extra in produced[1:]:
        extra.unlink()
    print("wrote", stable)


if __name__ == "__main__":
    gen_tb()
```

- [ ] **Step 2: Run the generator and confirm a real event file exists**

Run: `cd omx-core && python3 tests/fixtures/_gen_analyze_fixtures.py && ls -la tests/fixtures/tb/`
Expected: prints `wrote .../events.out.tfevents.synthetic`; file is non-empty.
If `tensorboard.summary.Writer` is unavailable in this TB version, fall back to `from torch.utils.tensorboard import SummaryWriter` is NOT allowed (no torch). Instead use the lower-level `tensorboard.compat.proto` event writer:
```python
from tensorboard.summary.writer.event_file_writer import EventFileWriter
from tensorboard.compat.proto import event_pb2, summary_pb2
def _scalar_event(tag, value, step):
    s = summary_pb2.Summary(value=[summary_pb2.Summary.Value(tag=tag, simple_value=value)])
    return event_pb2.Event(step=step, summary=s)
# writer = EventFileWriter(str(out_dir)); writer.add_event(_scalar_event(...)); writer.flush()
```
Verify which path works on this TB build BEFORE writing the test; use the one that produces a file `EventAccumulator` can read back (Step 4 proves it).

- [ ] **Step 3: Write the failing adapter test**

```python
# omx-core/tests/test_ingest_tensorboard.py
import numpy as np
import pytest
from omx_core.ingest import IngestAdapter, IngestResult
from omx_core.ingest.tensorboard import TensorboardAdapter


def _tb_fixture(fixtures_dir):
    return fixtures_dir / "tb" / "events.out.tfevents.synthetic"


def test_tb_adapter_is_adapter():
    assert isinstance(TensorboardAdapter(), IngestAdapter)


def test_tb_can_handle_event_filename():
    assert TensorboardAdapter().can_handle("/x/events.out.tfevents.123") is True
    assert TensorboardAdapter().can_handle("/x/summary.json") is False


def test_tb_ingest_fills_series_with_real_scalars(fixtures_dir):
    res = TensorboardAdapter().ingest(_tb_fixture(fixtures_dir))
    assert isinstance(res, IngestResult)
    # series keyed by TB tag; each a 1-D ndarray of the scalar values in step order
    assert "Reward/total" in res.series
    assert "Track/att/roll_err_deg" in res.series
    roll = res.series["Track/att/roll_err_deg"]
    assert isinstance(roll, np.ndarray) and roll.shape == (5,)
    assert np.isclose(roll[0], 20.0) and np.isclose(roll[-1], 12.0)
    # a parallel step index series is exposed so plots can use a real x-axis
    assert "_step/Track/att/roll_err_deg" in res.series
    assert res.series["_step/Track/att/roll_err_deg"].tolist() == [0, 1, 2, 3, 4]
    assert res.meta["format"] == "tensorboard"
    assert res.summary == []  # TB = curves (series), never long-form summary


def test_tb_ingest_loud_fails_on_missing_file(tmp_path):
    from omx_core.omx_paths import OmxError
    with pytest.raises((OmxError, FileNotFoundError, ValueError)):
        TensorboardAdapter().ingest(tmp_path / "events.out.tfevents.nope")
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_ingest_tensorboard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.ingest.tensorboard'`.

- [ ] **Step 5: Commit the fixture + failing test**

```bash
cd /workspace/oh-my-experiments
git add omx-core/tests/fixtures/_gen_analyze_fixtures.py omx-core/tests/fixtures/tb/ omx-core/tests/test_ingest_tensorboard.py
git commit -m "test(analyze): TB adapter fixtures + failing tests (build #4 task 1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Real TensorBoard adapter

**Files:**
- Create: `omx-core/omx_core/ingest/tensorboard.py`
- Test: `omx-core/tests/test_ingest_tensorboard.py` (from Task 1)

- [ ] **Step 1: Implement the adapter (deferred TB import, fills series)**

```python
# omx-core/omx_core/ingest/tensorboard.py
"""omx_core.ingest.tensorboard — real TB event-file adapter (build #4).

TB scalars are training/eval CURVES, so they fill IngestResult.series (named
1-D arrays), never .summary (which is long-form eval_dr stats). tensorboard is
an OPTIONAL dependency (extra 'analyze'); it is imported INSIDE ingest() so the
core stays importable without it. Uses EventAccumulator (pure-TB, no TensorFlow).
"""
from pathlib import Path

import numpy as np

from omx_core.ingest.base import IngestAdapter, IngestResult
from omx_core.omx_paths import OmxError


class TensorboardAdapter(IngestAdapter):
    def can_handle(self, path) -> bool:
        return "events.out.tfevents" in Path(path).name

    def ingest(self, path) -> IngestResult:
        path = Path(path)
        if not path.exists():
            raise OmxError(f"TB event file not found: {path}")
        try:
            from tensorboard.backend.event_processing import event_accumulator
        except ImportError as e:  # loud, actionable
            raise OmxError(
                "tensorboard not installed; `pip install omx-core[analyze]` to ingest TB"
            ) from e
        ea = event_accumulator.EventAccumulator(
            str(path), size_guidance={event_accumulator.SCALARS: 0})
        ea.Reload()
        tags = ea.Tags().get("scalars", [])
        series = {}
        for tag in tags:
            events = ea.Scalars(tag)
            series[tag] = np.array([e.value for e in events], dtype=float)
            series[f"_step/{tag}"] = np.array([e.step for e in events], dtype=float)
        return IngestResult(
            summary=[], series=series,
            meta={"source": str(path), "format": "tensorboard", "n_tags": len(tags)},
        )
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `cd omx-core && python3 -m pytest tests/test_ingest_tensorboard.py -v`
Expected: PASS (4 tests).

- [ ] **Step 3: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/omx_core/ingest/tensorboard.py
git commit -m "feat(analyze): real TensorBoard adapter via EventAccumulator (build #4 task 2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: WandB offline adapter + fixture

**Files:**
- Modify: `omx-core/tests/fixtures/_gen_analyze_fixtures.py` (add `gen_wandb()`)
- Create: `omx-core/tests/fixtures/wandb/run-synthetic.wandb` (generated)
- Create: `omx-core/omx_core/ingest/wandb_offline.py`
- Create: `omx-core/tests/test_ingest_wandb_offline.py`

- [ ] **Step 1: Add the wandb fixture generator**

Write a tiny real `.wandb` datastore log (no network) using the same datastore writer wandb uses internally.

```python
# append to _gen_analyze_fixtures.py
def gen_wandb():
    """Write a tiny REAL .wandb datastore log with 3 history records."""
    from wandb.sdk.internal import datastore
    from wandb.proto import wandb_internal_pb2 as pb
    out_dir = HERE / "wandb"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "run-synthetic.wandb"
    if target.exists():
        target.unlink()
    ds = datastore.DataStore()
    ds.open_for_write(str(target))
    for step in range(3):
        rec = pb.Record()
        h = rec.history
        it = h.item.add(); it.key = "Reward/total"; it.value_json = str(-0.5 + 0.1 * step)
        it2 = h.item.add(); it2.nested_key.extend(["Track", "att", "roll_err_deg"])
        it2.value_json = str(20.0 - 2.0 * step)
        st = h.step; st.num = step
        ds.write(rec)
    ds.close()
    print("wrote", target)
# in __main__: gen_tb(); gen_wandb()
```

- [ ] **Step 2: Generate and confirm offline readback**

Run:
```bash
cd omx-core && python3 tests/fixtures/_gen_analyze_fixtures.py && \
python3 -c "
from wandb.sdk.internal import datastore
from wandb.proto import wandb_internal_pb2 as pb
ds=datastore.DataStore(); ds.open_for_scan('tests/fixtures/wandb/run-synthetic.wandb')
n=0
while True:
    d=ds.scan_data()
    if d is None: break
    r=pb.Record(); r.ParseFromString(d)
    if r.WhichOneof('record_type')=='history': n+=1
print('history records:', n)
"
```
Expected: prints `history records: 3`. If `open_for_write`/`write` differ in this wandb version, inspect `datastore.DataStore` methods (`python3 -c "from wandb.sdk.internal import datastore; print([m for m in dir(datastore.DataStore) if not m.startswith('_')])"`) and adapt the writer; the READ side (Step 4) is the contract that must hold.

- [ ] **Step 3: Write the failing adapter test**

```python
# omx-core/tests/test_ingest_wandb_offline.py
import numpy as np
import pytest
from omx_core.ingest import IngestAdapter, IngestResult
from omx_core.ingest.wandb_offline import WandbAdapter


def _wandb_fixture(fixtures_dir):
    return fixtures_dir / "wandb" / "run-synthetic.wandb"


def test_wandb_adapter_is_adapter():
    assert isinstance(WandbAdapter(), IngestAdapter)


def test_wandb_can_handle_local_log():
    # accepts a path to a .wandb file or a wandb:// pointer at a local run dir
    assert WandbAdapter().can_handle("/x/run-abc.wandb") is True
    assert WandbAdapter().can_handle("wandb://run-abc") is True
    assert WandbAdapter().can_handle("/x/summary.json") is False


def test_wandb_ingest_offline_fills_series(fixtures_dir):
    res = WandbAdapter().ingest(_wandb_fixture(fixtures_dir))
    assert isinstance(res, IngestResult)
    assert "Reward/total" in res.series
    assert "Track/att/roll_err_deg" in res.series  # nested_key joined with '/'
    total = res.series["Reward/total"]
    assert isinstance(total, np.ndarray) and total.shape == (3,)
    assert np.isclose(total[0], -0.5) and np.isclose(total[-1], -0.3)
    assert res.meta["format"] == "wandb_offline"
    assert res.summary == []


def test_wandb_ingest_loud_fails_on_missing(tmp_path):
    from omx_core.omx_paths import OmxError
    with pytest.raises((OmxError, FileNotFoundError, ValueError)):
        WandbAdapter().ingest(tmp_path / "run-nope.wandb")
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_ingest_wandb_offline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.ingest.wandb_offline'`.

- [ ] **Step 5: Implement the adapter (offline datastore, deferred import)**

```python
# omx-core/omx_core/ingest/wandb_offline.py
"""omx_core.ingest.wandb_offline — WandB adapter, LOCAL OFFLINE logs only (build #4).

User decision 2026-05-30: WandB source = the on-disk `run-*.wandb` transaction log,
parsed via wandb.sdk.internal.datastore — NO network, NO auth, NO wandb.Api. This
keeps the core Claude-free AND deterministic (unit tests read a committed fixture).
History scalars become IngestResult.series (curves). wandb is an OPTIONAL dep
(extra 'analyze'), imported inside ingest().
"""
from collections import defaultdict
from pathlib import Path

import numpy as np

from omx_core.ingest.base import IngestAdapter, IngestResult
from omx_core.omx_paths import OmxError


class WandbAdapter(IngestAdapter):
    def can_handle(self, path) -> bool:
        p = str(path)
        return p.startswith("wandb://") or p.endswith(".wandb")

    def _resolve(self, path) -> Path:
        """Map a wandb:// pointer or a path to the concrete .wandb file.

        wandb://<x> where <x> is a local run dir name resolves to <x>/<x>.wandb is
        NOT attempted (no registry of run dirs in v0.1); the offline contract is a
        direct path to the .wandb file or a run dir containing exactly one."""
        p = Path(str(path).replace("wandb://", "", 1)) if str(path).startswith("wandb://") else Path(path)
        if p.is_dir():
            logs = sorted(p.glob("*.wandb"))
            if len(logs) != 1:
                raise OmxError(f"expected exactly one .wandb under {p}, found {len(logs)}")
            return logs[0]
        return p

    def ingest(self, path) -> IngestResult:
        wf = self._resolve(path)
        if not wf.exists():
            raise OmxError(f"wandb offline log not found: {wf}")
        try:
            from wandb.sdk.internal import datastore
            from wandb.proto import wandb_internal_pb2 as pb
        except ImportError as e:
            raise OmxError(
                "wandb not installed; `pip install omx-core[analyze]` to ingest wandb logs"
            ) from e
        ds = datastore.DataStore()
        ds.open_for_scan(str(wf))
        cols = defaultdict(list)
        while True:
            data = ds.scan_data()
            if data is None:
                break
            rec = pb.Record()
            rec.ParseFromString(data)
            if rec.WhichOneof("record_type") != "history":
                continue
            for item in rec.history.item:
                key = item.key or "/".join(item.nested_key)
                if not key:
                    continue
                try:
                    cols[key].append(float(item.value_json))
                except (ValueError, TypeError):
                    # non-numeric history values (strings/objects) are not curves; skip
                    continue
        if not cols:
            raise OmxError(f"no numeric history scalars in wandb log {wf}")
        series = {k: np.array(v, dtype=float) for k, v in cols.items()}
        return IngestResult(
            summary=[], series=series,
            meta={"source": str(wf), "format": "wandb_offline", "n_keys": len(series)},
        )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd omx-core && python3 -m pytest tests/test_ingest_wandb_offline.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/tests/fixtures/_gen_analyze_fixtures.py omx-core/tests/fixtures/wandb/ \
        omx-core/omx_core/ingest/wandb_offline.py omx-core/tests/test_ingest_wandb_offline.py
git commit -m "feat(analyze): offline WandB adapter via datastore log (build #4 task 3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Retire the stubs, wire the real adapters into ingest + CLI

**Files:**
- Delete: `omx-core/omx_core/ingest/stubs.py`
- Modify: `omx-core/tests/test_ingest_stubs.py` (re-point imports OR delete + rely on new tests)
- Modify: `omx-core/omx_core/cli.py` (`_ADAPTERS`)
- Test: `omx-core/tests/test_cli.py` (add ingest-by-format cases)

- [ ] **Step 1: Write the failing CLI test**

```python
# add to omx-core/tests/test_cli.py
def test_cli_ingest_tensorboard(fixtures_dir, capsys):
    from omx_core.cli import main
    ev = fixtures_dir / "tb" / "events.out.tfevents.synthetic"
    rc = main(["ingest", "--path", str(ev), "--format", "tensorboard"])
    assert rc == 0
    import json
    out = json.loads(capsys.readouterr().out)
    assert out["format"] == "tensorboard"
    assert out["n_series"] >= 2


def test_cli_ingest_wandb_offline(fixtures_dir, capsys):
    from omx_core.cli import main
    wf = fixtures_dir / "wandb" / "run-synthetic.wandb"
    rc = main(["ingest", "--path", str(wf), "--format", "wandb"])
    assert rc == 0
    import json
    out = json.loads(capsys.readouterr().out)
    assert out["format"] == "wandb_offline"
    assert out["n_series"] >= 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_cli.py -k "tensorboard or wandb" -v`
Expected: FAIL — `unknown --format 'tensorboard'`.

- [ ] **Step 3: Register adapters; delete stubs; fix stub-test imports**

In `cli.py`, extend `_ADAPTERS`:
```python
from omx_core.ingest.eval_summary import EvalSummaryAdapter
from omx_core.ingest.csv_longform import LongFormCsvAdapter
from omx_core.ingest.tensorboard import TensorboardAdapter
from omx_core.ingest.wandb_offline import WandbAdapter

_ADAPTERS = {
    "eval_summary": EvalSummaryAdapter,
    "csv_longform": LongFormCsvAdapter,
    "tensorboard": TensorboardAdapter,
    "wandb": WandbAdapter,
}
```

Delete `omx-core/omx_core/ingest/stubs.py`. Then rewrite `tests/test_ingest_stubs.py` to import from the real modules and drop the `NotImplementedError`/`build #4` assertions (those described the stub, which no longer exists):
```python
# omx-core/tests/test_ingest_stubs.py  (now: adapter-contract smoke test)
from omx_core.ingest import IngestAdapter
from omx_core.ingest.tensorboard import TensorboardAdapter
from omx_core.ingest.wandb_offline import WandbAdapter


def test_real_adapters_are_adapters():
    assert isinstance(WandbAdapter(), IngestAdapter)
    assert isinstance(TensorboardAdapter(), IngestAdapter)


def test_can_handle_routing():
    assert WandbAdapter().can_handle("wandb://run") is True
    assert WandbAdapter().can_handle("/x/run-a.wandb") is True
    assert TensorboardAdapter().can_handle("/x/events.out.tfevents.1") is True
    assert TensorboardAdapter().can_handle("/x/summary.json") is False
```
(Rename intent: keep the filename to avoid churn, but it is no longer a "stubs" test. A separate quality-review note will flag whether to rename the file to `test_ingest_network_adapters.py` — leave that to the reviewer; do not rename here to keep the diff tight.)

- [ ] **Step 4: Run the full ingest + CLI suite**

Run: `cd omx-core && python3 -m pytest tests/test_cli.py tests/test_ingest_stubs.py tests/test_ingest_tensorboard.py tests/test_ingest_wandb_offline.py -v`
Expected: PASS. No reference to a deleted `stubs` symbol remains (grep): `grep -rn "ingest.stubs\|NotImplementedError" omx-core/omx_core omx-core/tests` returns nothing in non-test code.

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add -A omx-core/omx_core/ingest/ omx-core/omx_core/cli.py omx-core/tests/test_ingest_stubs.py omx-core/tests/test_cli.py
git commit -m "feat(analyze): wire TB+wandb adapters into CLI, retire stubs (build #4 task 4)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Profile loader (`metrics.yaml` → `omx_paths.Profile`)

**Files:**
- Modify: `omx-core/omx_core/profile.py` (add `load_profile`)
- Test: `omx-core/tests/test_profile_load.py`

- [ ] **Step 1: Write the failing test**

```python
# omx-core/tests/test_profile_load.py
import pytest
from omx_core.omx_paths import OmxPaths, Profile, OmxError
from omx_core.profile import bootstrap_profile, load_profile, default_metrics


def _bootstrap(root):
    paths = OmxPaths(root=root)
    bootstrap_profile(paths, profile_name="isaaclab", metrics=default_metrics())
    return paths


def test_load_profile_builds_vocabulary_tier(tmp_path):
    _bootstrap(tmp_path)
    prof = load_profile(tmp_path)
    assert isinstance(prof, Profile)
    assert "ss_error" in prof.metrics
    assert "trajectory" in prof.views
    assert "by_axis" in prof.aggs
    assert "eval_summary" in prof.sources
    assert prof.run_id_regex is None


def test_loaded_profile_enforces_vocab_in_paths(tmp_path):
    _bootstrap(tmp_path)
    prof = load_profile(tmp_path)
    paths = OmxPaths(root=tmp_path, profile=prof)
    # in-vocab metric/view OK
    p = paths.analysis_plot("experiments", "run1", "20260530-101010-compare",
                            metric="ss_error", view="trajectory")
    assert p.name == "ss_error__trajectory.png"
    # out-of-vocab metric loud-fails (vocabulary tier active)
    with pytest.raises(OmxError):
        paths.analysis_plot("experiments", "run1", "20260530-101010-compare",
                            metric="not_a_metric", view="trajectory")


def test_load_profile_missing_raises(tmp_path):
    with pytest.raises(OmxError):
        load_profile(tmp_path)  # no .omx/profile/metrics.yaml
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_profile_load.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_profile'`.

- [ ] **Step 3: Implement `load_profile`**

```python
# add to omx-core/omx_core/profile.py (imports: Path already? add `from pathlib import Path`)
def load_profile(root) -> "Profile":
    """Read .omx/profile/metrics.yaml under `root` and build an omx_paths.Profile.

    Activates the B1 vocabulary tier for exp-analyze: metric/view/agg/source are
    drawn from the profile's closed vocab, run_id from its regex. Loud-fails if the
    profile is absent or its metrics.yaml violates the schema (re-validated here so
    a hand-edited file can't smuggle a bad vocab into path validation).
    """
    paths = root if isinstance(root, OmxPaths) else OmxPaths(root=root)
    metrics_path = paths.profile_file("metrics.yaml")
    if not metrics_path.exists():
        raise OmxError(f"no profile at {metrics_path}; run exp-init first")
    data = yaml.safe_load(metrics_path.read_text())
    if not isinstance(data, dict):
        raise OmxError(f"metrics.yaml at {metrics_path} did not parse to a mapping")
    # validate_metrics_schema requires pending_approval=True (a fresh-profile
    # invariant). An APPROVED profile has flipped/removed that key, so re-running
    # the bootstrap validator would wrongly reject it. Validate only the fields the
    # vocabulary tier consumes, here, without the bootstrap-only pending_approval rule.
    for field in _VOCAB_FIELDS:
        seq = data.get(field)
        if not isinstance(seq, list) or not seq:
            raise OmxError(f"metrics.yaml: {field} must be a non-empty list")
    return Profile(
        metrics=set(data["metrics"]),
        views=set(data["views"]),
        aggs=set(data["aggs"]),
        sources=set(data["sources"]),
        run_id_regex=data.get("run_id_regex"),
    )
```
Add `from pathlib import Path` to the imports only if not already imported (it is not — `profile.py` currently imports `shutil`, `yaml`, and omx_paths symbols; `Path` is unused by this function since `paths.profile_file` returns a Path, so DO NOT add an unused import).

- [ ] **Step 4: Run to verify it passes**

Run: `cd omx-core && python3 -m pytest tests/test_profile_load.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/omx_core/profile.py omx-core/tests/test_profile_load.py
git commit -m "feat(analyze): load_profile activates B1 vocabulary tier (build #4 task 5)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: B3 plot promotion core function

**Files:**
- Create: `omx-core/omx_core/reduce/promote.py`
- Modify: `omx-core/omx_core/reduce/__init__.py`
- Test: `omx-core/tests/test_reduce_promote.py`

- [ ] **Step 1: Write the failing test**

```python
# omx-core/tests/test_reduce_promote.py
import pytest
from omx_core.reduce.promote import promote_plots
from omx_core.omx_paths import OmxError


def _png(path, body=b"\x89PNG\r\n\x1a\n0"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def test_promotes_only_referenced(tmp_path):
    scratch = tmp_path / "scratch" / "plots"
    dest = tmp_path / "analysis" / "plots"
    _png(scratch / "ss_error__trajectory.png", b"REFA")
    _png(scratch / "attitude__overlay.png", b"REFB")
    _png(scratch / "unused__bar.png", b"NOPE")
    moved = promote_plots(scratch, dest, ["ss_error__trajectory.png", "attitude__overlay.png"])
    assert sorted(p.name for p in moved) == ["attitude__overlay.png", "ss_error__trajectory.png"]
    # referenced moved to dest...
    assert (dest / "ss_error__trajectory.png").read_bytes() == b"REFA"
    assert (dest / "attitude__overlay.png").exists()
    # ...and removed from scratch (os.replace moves)
    assert not (scratch / "ss_error__trajectory.png").exists()
    # unreferenced stays in scratch for omx clean
    assert (scratch / "unused__bar.png").read_bytes() == b"NOPE"
    assert not (dest / "unused__bar.png").exists()


def test_missing_referenced_loud_fails(tmp_path):
    scratch = tmp_path / "scratch" / "plots"
    dest = tmp_path / "analysis" / "plots"
    _png(scratch / "real.png")
    with pytest.raises(OmxError, match="ghost.png"):
        promote_plots(scratch, dest, ["real.png", "ghost.png"])
    # atomic-ish: the loud-fail happens BEFORE any move (real.png not yet promoted)
    assert (scratch / "real.png").exists()
    assert not (dest / "real.png").exists()


def test_empty_referenced_promotes_nothing(tmp_path):
    scratch = tmp_path / "scratch" / "plots"
    dest = tmp_path / "analysis" / "plots"
    _png(scratch / "a.png")
    assert promote_plots(scratch, dest, []) == []
    assert not dest.exists() or not any(dest.iterdir())
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_reduce_promote.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.reduce.promote'`.

- [ ] **Step 3: Implement `promote_plots`**

```python
# omx-core/omx_core/reduce/promote.py
"""omx_core.reduce.promote — B3 plot promotion (scratch -> permanent).

exp-analyze writes ALL candidate PNGs to scratch/<sid>/plots/; only those the
final report.md references are promoted into the permanent analysis/<aid>/plots/
tree (atomic os.replace). Unreferenced candidates stay in scratch for omx clean.
This is the single rule that keeps the permanent output tree clean (design B3/10.1).
"""
import os
from pathlib import Path

from omx_core.omx_paths import OmxError


def promote_plots(scratch_plots_dir, dest_plots_dir, referenced) -> list:
    """Move each referenced PNG from scratch_plots_dir to dest_plots_dir.

    referenced = list of bare filenames (e.g. 'ss_error__trajectory.png') that the
    report.md cites. Loud-fails (before moving anything) if a referenced file is
    absent in scratch — a report citing a plot that was never rendered is a bug, not
    a silent skip. Returns the list of destination Paths. Unreferenced scratch files
    are left untouched.
    """
    scratch = Path(scratch_plots_dir)
    dest = Path(dest_plots_dir)
    # Pre-flight: verify every referenced file exists BEFORE any move (no partial promotion).
    missing = [name for name in referenced if not (scratch / name).exists()]
    if missing:
        raise OmxError(
            f"report references plot(s) not found in scratch {scratch}: {missing}")
    if not referenced:
        return []
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    for name in referenced:
        target = dest / name
        os.replace(scratch / name, target)  # atomic within a filesystem
        moved.append(target)
    return moved
```

Export it:
```python
# omx-core/omx_core/reduce/__init__.py — add to imports + __all__
from omx_core.reduce.promote import promote_plots
# __all__ += ["promote_plots"]
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd omx-core && python3 -m pytest tests/test_reduce_promote.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/omx_core/reduce/promote.py omx-core/omx_core/reduce/__init__.py omx-core/tests/test_reduce_promote.py
git commit -m "feat(analyze): B3 plot promotion (scratch->permanent, loud on missing) (build #4 task 6)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `omx plot` CLI verb (series source → candidate PNG in scratch)

**Files:**
- Modify: `omx-core/omx_core/cli.py` (add `_cmd_plot`, subparser)
- Test: `omx-core/tests/test_cli_plot.py`

This verb lets the skill render a candidate curve PNG from an ingestable series source WITHOUT writing its own matplotlib — the skill stays a thin Claude wrapper; plot file IO is core (D8). Output goes to `scratch/<sid>/plots/<metric>__<view>.png`.

- [ ] **Step 1: Write the failing test**

```python
# omx-core/tests/test_cli_plot.py
import json
from omx_core.cli import main


def _png_ok(path):
    return path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_cli_plot_line_from_tb_to_scratch(fixtures_dir, tmp_path, capsys):
    ev = fixtures_dir / "tb" / "events.out.tfevents.synthetic"
    rc = main([
        "plot", "--root", str(tmp_path), "--session-id", "20260530-101010-1",
        "--path", str(ev), "--format", "tensorboard",
        "--series", "Track/att/roll_err_deg", "--metric", "attitude", "--view", "trajectory",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    from pathlib import Path
    png = Path(out["plot"])
    # lands in scratch/<sid>/plots/<metric>__<view>.png (NOT permanent tree)
    assert png.parts[-3:] == ("plots", ) or "scratch" in str(png)
    assert png.name == "attitude__trajectory.png"
    assert "scratch" in str(png)
    assert _png_ok(png)


def test_cli_plot_unknown_series_loud_fails(fixtures_dir, tmp_path):
    ev = fixtures_dir / "tb" / "events.out.tfevents.synthetic"
    rc = main([
        "plot", "--root", str(tmp_path), "--session-id", "20260530-101010-1",
        "--path", str(ev), "--format", "tensorboard",
        "--series", "Nope/missing", "--metric", "attitude", "--view", "trajectory",
    ])
    assert rc == 2  # loud-fail via SystemExit -> rc 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_cli_plot.py -v`
Expected: FAIL — `invalid choice: 'plot'`.

- [ ] **Step 3: Implement `_cmd_plot` + subparser**

```python
# add to omx-core/omx_core/cli.py
from omx_core.reduce.series import downsample
from omx_core.reduce.plot import line_plot
from omx_core.omx_paths import OmxPaths as _OmxPaths  # already imported as OmxPaths
import numpy as _np


def _cmd_plot(args) -> int:
    """Render ONE candidate curve from a series source into scratch/<sid>/plots/.

    Claude-free: the skill picks WHICH series/metric/view; this verb does the
    matplotlib + scratch-path IO (design D8). Output filename = <metric>__<view>.png.
    """
    res = _ingest(args.path, args.format)
    if args.series not in res.series:
        raise SystemExit(
            f"series {args.series!r} not in source; available: {sorted(res.series)[:20]}")
    y = downsample(res.series[args.series])
    step_key = f"_step/{args.series}"
    x = downsample(res.series[step_key]) if step_key in res.series else _np.arange(len(y))
    paths = OmxPaths(root=args.root)
    # metric/view validated by analysis_plot's token check; here we only build the
    # scratch path, so validate the tokens directly via the same rule.
    from omx_core.omx_paths import validate_token
    metric = validate_token(args.metric, "metric")
    view = validate_token(args.view, "view")
    out = paths.scratch_plots(session_id=args.session_id) / f"{metric}__{view}.png"
    line_plot(x, {args.series: y}, out, title=f"{metric} ({view})")
    print(json.dumps({"plot": str(out), "metric": metric, "view": view,
                      "n_points": int(len(y))}))
    return 0
```
Register in `build_parser()`:
```python
    pp = sub.add_parser("plot", help="render a candidate curve PNG into scratch (Claude-free IO)")
    pp.add_argument("--root", required=True, help="anchor dir under which .omx/ lives")
    pp.add_argument("--session-id", required=True, dest="session_id")
    pp.add_argument("--path", required=True, help="series source (npz/TB/wandb)")
    pp.add_argument("--format", required=True)
    pp.add_argument("--series", required=True, help="series key within the source")
    pp.add_argument("--metric", required=True, help="metric token (output filename field)")
    pp.add_argument("--view", required=True, help="view token (output filename field)")
    pp.set_defaults(func=_cmd_plot)
```
Note: `--format npz` needs an adapter. The npz path is NOT an IngestAdapter today (`load_npz` is a reduce helper). For Task 7, `--format` accepts the existing `_ADAPTERS` keys (tensorboard/wandb/eval_summary/csv_longform). npz trajectory plotting is reached by the skill calling `load_npz` is NOT available via CLI — so add a tiny `npz` pseudo-format branch in `_ingest` that wraps `load_npz` into an IngestResult.series. Implement that branch:
```python
def _ingest(path, fmt):
    if fmt == "npz":
        from omx_core.reduce.series import load_npz
        arrs = load_npz(path)
        # only 1-D numeric arrays are plottable series; keep those
        series = {k: v for k, v in arrs.items() if getattr(v, "ndim", 0) == 1}
        from omx_core.ingest.base import IngestResult
        return IngestResult(summary=[], series=series, meta={"source": str(path), "format": "npz"})
    if fmt not in _ADAPTERS:
        raise SystemExit(f"unknown --format {fmt!r}; choose from {sorted(_ADAPTERS) + ['npz']}")
    return _ADAPTERS[fmt]().ingest(path)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd omx-core && python3 -m pytest tests/test_cli_plot.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/omx_core/cli.py omx-core/tests/test_cli_plot.py
git commit -m "feat(analyze): omx plot verb renders candidate PNG to scratch (build #4 task 7)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: `omx promote-plots` CLI verb (B3 promotion from the CLI)

**Files:**
- Modify: `omx-core/omx_core/cli.py` (add `_cmd_promote`, subparser)
- Test: `omx-core/tests/test_cli_promote.py`

- [ ] **Step 1: Write the failing test**

```python
# omx-core/tests/test_cli_promote.py
import json
from pathlib import Path
from omx_core.cli import main


def _png(p, body=b"\x89PNG\r\n\x1a\n0"):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(body); return p


def test_cli_promote_moves_referenced(tmp_path, capsys):
    # scratch lives under the omx root the verb computes from --root/--session-id
    from omx_core.omx_paths import OmxPaths
    paths = OmxPaths(root=tmp_path)
    sp = paths.scratch_plots(session_id="20260530-101010-1")
    _png(sp / "ss_error__trajectory.png", b"KEEP")
    _png(sp / "unused__bar.png", b"DROP")
    rc = main([
        "promote-plots", "--root", str(tmp_path), "--session-id", "20260530-101010-1",
        "--output-root", str(tmp_path / "experiments"), "--run-id", "run1",
        "--analysis-id", "20260530-101010-compare",
        "--referenced", "ss_error__trajectory.png",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    dest = Path(out["promoted"][0])
    assert dest.read_bytes() == b"KEEP"
    assert dest.parts[-2:] == ("plots", "ss_error__trajectory.png") or dest.name == "ss_error__trajectory.png"
    assert "analysis" in str(dest) and "20260530-101010-compare" in str(dest)
    # unreferenced remains in scratch
    assert (sp / "unused__bar.png").exists()


def test_cli_promote_missing_loud_fails(tmp_path):
    from omx_core.omx_paths import OmxPaths
    paths = OmxPaths(root=tmp_path)
    paths.scratch_plots(session_id="20260530-101010-1").mkdir(parents=True)
    rc = main([
        "promote-plots", "--root", str(tmp_path), "--session-id", "20260530-101010-1",
        "--output-root", str(tmp_path / "experiments"), "--run-id", "run1",
        "--analysis-id", "20260530-101010-compare",
        "--referenced", "ghost.png",
    ])
    assert rc == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd omx-core && python3 -m pytest tests/test_cli_promote.py -v`
Expected: FAIL — `invalid choice: 'promote-plots'`.

- [ ] **Step 3: Implement `_cmd_promote` + subparser**

```python
# add to omx-core/omx_core/cli.py
from omx_core.reduce.promote import promote_plots


def _cmd_promote(args) -> int:
    """Promote report-referenced PNGs from scratch into the permanent analysis tree (B3).

    --referenced may be repeated. Loud-fails (rc 2) if any referenced PNG is absent
    in scratch (handled by promote_plots raising OmxError -> SystemExit)."""
    paths = OmxPaths(root=args.root)
    scratch = paths.scratch_plots(session_id=args.session_id)
    dest = paths.analysis_dir(args.output_root, args.run_id, args.analysis_id) / "plots"
    try:
        moved = promote_plots(scratch, dest, args.referenced)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps({"promoted": [str(p) for p in moved]}))
    return 0
```
Register:
```python
    pm = sub.add_parser("promote-plots", help="B3: move report-referenced PNGs scratch->permanent")
    pm.add_argument("--root", required=True)
    pm.add_argument("--session-id", required=True, dest="session_id")
    pm.add_argument("--output-root", required=True, dest="output_root")
    pm.add_argument("--run-id", required=True, dest="run_id")
    pm.add_argument("--analysis-id", required=True, dest="analysis_id")
    pm.add_argument("--referenced", action="append", default=[],
                    help="a report-referenced PNG filename; repeat for multiple")
    pm.set_defaults(func=_cmd_promote)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd omx-core && python3 -m pytest tests/test_cli_promote.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Full suite green**

Run: `cd omx-core && python3 -m pytest -q`
Expected: all prior + new tests PASS (no regressions). Record the count.

- [ ] **Step 6: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/omx_core/cli.py omx-core/tests/test_cli_promote.py
git commit -m "feat(analyze): omx promote-plots verb (B3 from CLI) (build #4 task 8)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: optional-dependencies extra + import-safety guard

**Files:**
- Modify: `omx-core/pyproject.toml`
- Test: `omx-core/tests/test_core_import_safe.py`

- [ ] **Step 1: Write the failing test**

The core must import WITHOUT wandb/tensorboard present (they are deferred). Prove the package import path never eagerly pulls them.

```python
# omx-core/tests/test_core_import_safe.py
import subprocess
import sys


def test_core_imports_without_eager_heavy_deps():
    # importing the package + cli must NOT import wandb/tensorboard at module load
    code = (
        "import omx_core, omx_core.cli, omx_core.ingest.tensorboard, "
        "omx_core.ingest.wandb_offline, sys; "
        "assert 'wandb' not in sys.modules, 'wandb imported eagerly'; "
        "assert 'tensorboard' not in sys.modules, 'tensorboard imported eagerly'; "
        "print('OK')"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "OK" in r.stdout
```

- [ ] **Step 2: Run to verify it fails OR passes**

Run: `cd omx-core && python3 -m pytest tests/test_core_import_safe.py -v`
Expected: PASS if the deferred-import discipline from Tasks 2/3 held (imports are inside `ingest()`). If it FAILS (something imports wandb/tensorboard at module top), fix the offending module to defer the import, then re-run. This test is the guard that the Claude-free core stays lightweight.

- [ ] **Step 3: Add the optional-dependencies extra**

```toml
# omx-core/pyproject.toml — add after [project] dependencies block
[project.optional-dependencies]
analyze = ["wandb>=0.18", "tensorboard>=2.14"]
```

- [ ] **Step 4: Re-run to confirm green**

Run: `cd omx-core && python3 -m pytest tests/test_core_import_safe.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/pyproject.toml omx-core/tests/test_core_import_safe.py
git commit -m "feat(analyze): analyze extra + import-safety guard for heavy deps (build #4 task 9)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: `exp-analyze` SKILL.md (the Claude hybrid router)

**Files:**
- Create: `skills/exp-analyze/SKILL.md`

This is the Claude-required layer. It orchestrates the Claude-free verbs and applies the §5 hybrid router. It does NOT contain Python — it instructs Claude how to drive the core + read PNGs + write the report.

- [ ] **Step 1: Write the skill**

```markdown
---
name: exp-analyze
description: Analyze N existing experiment/training runs into an evidence-tagged report. Use when comparing runs, reading eval/training curves, or diagnosing why a run regressed — the hybrid router decides per question whether to use exact code-exec stats, a vision-read PNG curve, or both. Reads the OMX profile (metrics.yaml) for the metric vocabulary. Writes report.md + promoted plots into the permanent analysis tree. Never launches training or eval. Triggers on "analyze these runs", "compare run A and B", "why did this regress", "런 분석", "eval plot 보여줘".
argument-hint: "[--root <dir>] <run ids or result paths to analyze>"
---

# exp-analyze — hybrid PNG-vision + code-exec run analysis

## Overview

`exp-analyze` analyzes results that ALREADY EXIST. It never launches training or
eval (design D4/B8). It reads the OMX profile written by exp-init, then runs the
hybrid router (design §5) to answer each analysis question with the cheapest
sufficient evidence, and writes a single human deliverable: `report.md` (+ the
plots it references) in the permanent analysis tree.

**Announce at start:** "Using exp-analyze to analyze the runs and write an evidence-tagged report."

## Preconditions (check, don't assume)

1. A profile exists and is approved. Read `<root>/.omx/profile/metrics.yaml`. If it
   is missing → tell the user to run exp-init first; STOP. If `pending_approval: true`
   is still set → tell the user to approve it first; STOP. (Honors the exp-init hard gate.)
2. The runs to analyze exist on disk. The user names run ids or result paths
   (eval_dr summary.json, TB event files, wandb run dirs, data_*.npz). Resolve them;
   if a path is missing, say so and STOP — never fabricate data.

## Session id (for scratch isolation, B2)

Resolve once at start: `omx session-id --session-id "<claude session id if known>"`.
Pass the printed id as `--session-id` to every `omx plot` / `omx promote-plots` call
so this analysis's candidate plots stay isolated under `scratch/<sid>/plots/`.

## The hybrid router (design §5 — the core IP)

For EACH analysis question, pick the evidence type by the question's nature. Never
put raw CSV/tables in context — that is the failure mode this router prevents.

| Question type | Tool | How |
|:--|:--|:--|
| exact numbers (mean, CV=std/mean, per-axis max, slope, pass/score) | **code-exec** | `omx reduce summarize --path <summary.json> --format eval_summary --cv-field <metric>` → exact JSON. For TB/wandb curves, `omx ingest`/`omx plot` then compute in a scratch script under `scratch/<sid>/py/` (write via the core path, run with python3). |
| shape / convergence point / divergence span / heavy-tail tail | **PNG-vision** | `omx plot --root <root> --session-id <sid> --path <src> --format <fmt> --series <key> --metric <m> --view <v>` → renders a candidate PNG into scratch; then READ that PNG with the vision tool and describe the shape. |
| where two runs diverged (aligned) | **PNG overlay OR code stride-extract** | overlay: plot both series on one figure (visual point); exact iter: stride-extract in a scratch script. |
| one-line verdict (pass/score) | **code-exec → JSON scalar** | `omx eval ...` (only if the profile's evaluator is approved; NEVER auto-launch a live eval — read an existing verdict if present). |

Pipeline discipline: **summary-stat-first → PNG only if it's a shape question →
code-exec to verify any precise claim.** A claim about a number must trace to a
code-exec output, never to eyeballing a PNG (repo rule: 추측 금지, 코드/데이터로 증명).

## Evidence tags (mandatory in report.md — design §1, sciomc pattern)

Every finding is tagged:
- `[FINDING]` — the claim, one line.
- `[EVIDENCE: <source>]` — the file/command that proves it (e.g. `summary.json hard/roll/ss_error=0.76`, or `Reward/total curve, scratch plot`).
- `[CONFIDENCE: HIGH|MED|LOW]` — HIGH = exact code-exec number or a clear PNG shape; MED = inference across sources; LOW = speculation (avoid — prefer to gather more evidence).

A finding with a numeric claim and `[CONFIDENCE: HIGH]` MUST cite a code-exec source, not a PNG.

## Building the report (permanent tree, via the core — never hand-write paths)

1. Choose an `analysis_id` = `<YYYYMMDD-HHMMSS>-<verb>` (verb = lowercase, e.g. `compare`, `diagnose`). Get the timestamp from `date +%Y%m%d-%H%M%S` via Bash.
2. Resolve `output_root` from the profile's `metrics.yaml`.
3. Draft `report.md` referencing ONLY the plots you actually used (by bare filename, e.g. `![](plots/ss_error__trajectory.png)`).
4. Promote the referenced plots: `omx promote-plots --root <root> --session-id <sid> --output-root <output_root> --run-id <run_id> --analysis-id <analysis_id> --referenced <name> [--referenced <name> ...]`. This moves them from scratch into `analysis/<analysis_id>/plots/`. If it loud-fails on a missing plot, you referenced a plot you never rendered — fix the report or render it.
5. Write `report.md` into the permanent tree. The path comes from the core:
   `python3 -c "from omx_core.omx_paths import OmxPaths; print(OmxPaths(root='<root>').report_md('<output_root>','<run_id>','<analysis_id>'))"` then write the file there (its parent already exists after promotion, or create via the core).
6. Write `manifest.json` next to it: `{inputs:[...resolved result paths...], profile_hash, omx_version, git_sha, analysis_id, generated_by:"exp-analyze"}`. Get git_sha via `git -C <repo> rev-parse --short HEAD` if in a repo; else `"n/a"`.

## Hard constraints (never violate)

- NEVER launch training or eval (no `launch.sh`, no live eval_dr). Analysis reads existing results only.
- NEVER write a path by hand; every `.omx/`/output path comes from an `omx` verb or `omx_paths` getter.
- NEVER claim a number you did not get from code-exec. PNG vision is for SHAPE, not digits.
- Candidate plots that the report doesn't reference are LEFT in scratch (omx clean sweeps them) — do not delete them yourself.
- Respond to the user in Korean (repo rule); keep report.md/code/markdown in English.

## When done

Tell the user where the report is (`<output_root>/<run_id>/analysis/<analysis_id>/report.md`),
summarize the top findings (with their confidence), and STOP. Do not propose or
launch a next experiment — that is exp-design's job (#5).
```

- [ ] **Step 2: Validate the skill frontmatter parses**

Run: `cd /workspace/oh-my-experiments && python3 -c "
import re, pathlib
t = pathlib.Path('skills/exp-analyze/SKILL.md').read_text()
assert t.startswith('---'), 'missing frontmatter'
fm = t.split('---', 2)[1]
assert 'name: exp-analyze' in fm and 'description:' in fm
print('frontmatter OK')
"`
Expected: `frontmatter OK`.

- [ ] **Step 3: Commit**

```bash
cd /workspace/oh-my-experiments
git add skills/exp-analyze/SKILL.md
git commit -m "feat(analyze): exp-analyze skill (hybrid router, evidence tags, B3 promotion) (build #4 task 10)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Register skill in plugin.json + end-to-end smoke + HANDOFF update

**Files:**
- Modify: `.claude-plugin/plugin.json`
- Modify: `docs/HANDOFF.md`
- Test: manual end-to-end smoke (documented commands)

- [ ] **Step 1: Register the skill**

In `.claude-plugin/plugin.json`, change:
```json
  "skills": [
    "./skills/exp-init/"
  ]
```
to:
```json
  "skills": [
    "./skills/exp-init/",
    "./skills/exp-analyze/"
  ]
```

- [ ] **Step 2: End-to-end smoke (real fixtures, no Claude)**

Prove the Claude-free spine the skill rides on works end-to-end:
```bash
cd /workspace/oh-my-experiments/omx-core
T=$(mktemp -d)
# 1. bootstrap a profile (so load_profile + vocab tier are exercised)
python3 -m omx_core.cli init --root "$T" --profile-name isaaclab \
  --metrics-json '{"pending_approval":true,"output_root":"experiments","metrics":["attitude","ss_error","survival_pct","lin_vel"],"views":["trajectory","per_axis_bar","overlay"],"aggs":["by_axis","mean_std"],"sources":["eval_summary","tensorboard","wandb"],"run_id_regex":null,"keep_policy":"pass_only","score_formula":null}'
# 2. ingest a real TB file -> series counts
python3 -m omx_core.cli ingest --path tests/fixtures/tb/events.out.tfevents.synthetic --format tensorboard
# 3. ingest the offline wandb log
python3 -m omx_core.cli ingest --path tests/fixtures/wandb/run-synthetic.wandb --format wandb
# 4. render a candidate plot into scratch
python3 -m omx_core.cli plot --root "$T" --session-id 20260530-101010-1 \
  --path tests/fixtures/tb/events.out.tfevents.synthetic --format tensorboard \
  --series "Track/att/roll_err_deg" --metric attitude --view trajectory
# 5. promote it into the permanent tree
python3 -m omx_core.cli promote-plots --root "$T" --session-id 20260530-101010-1 \
  --output-root "$T/experiments" --run-id run1 --analysis-id 20260530-101010-compare \
  --referenced attitude__trajectory.png
# 6. confirm the promoted plot exists and scratch no longer holds it
ls "$T/experiments/run1/analysis/20260530-101010-compare/plots/"
echo "--- smoke OK ---"
rm -rf "$T"
```
Expected: each command prints JSON/values without error; the final `ls` shows `attitude__trajectory.png`; prints `--- smoke OK ---`.

- [ ] **Step 3: Full suite + count**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest -q`
Expected: all tests PASS (record the new total; should be 252 + new analyze tests).

- [ ] **Step 4: Update HANDOFF**

In `docs/HANDOFF.md`, under "다음에 할 일", mark build #4 done with: branch `feat/omx-exp-analyze`, what was built (TB+wandb offline adapters, load_profile vocab tier, B3 promote, `omx plot`/`promote-plots` verbs, exp-analyze skill), test count, and that WandbAdapter/TensorboardAdapter stubs are now real. Note plugin.json now lists 2 skills. NEXT = #5 exp-design.

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add .claude-plugin/plugin.json docs/HANDOFF.md
git commit -m "feat(plugin): register exp-analyze; mark build #4 done (build #4 task 11)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (run after the plan is written — done)

**1. Spec coverage:**
- §4 exp-analyze role (hybrid router, report.md in permanent tree, promoted PNGs, evidence tags) → Task 10 (skill) + Tasks 6–8 (promotion core/CLI).
- §4 "Claude-free = {ingest, reduce, eval}; analyze = thin Claude wrapper" → Tasks 2/3/6/7/8 are core (Claude-free), Task 10 is the wrapper. No `omx analyze` verb (correct — analysis is Claude's judgment).
- §5 hybrid router (4 branches) → Task 10 router table, verbatim from §5.
- §10.1 B3 plot promotion (scratch → permanent, only referenced, os.replace) → Task 6 (`promote_plots`) + Task 8 (`omx promote-plots`) + Task 10 step 4.
- §10.1 permanent tree layout (`<output_root>/<run_id>/analysis/<analysis_id>/{report.md,plots,tables,manifest.json}`) → uses existing `omx_paths` getters (analysis_dir/report_md/manifest_json/analysis_plot); Task 8 + Task 10.
- B1 vocabulary tier activation (metric/view ∈ metrics.yaml) → Task 5 (`load_profile`) builds the `Profile`; Task 10 reads it.
- WandbAdapter/TensorboardAdapter real impl, validated on real data → Tasks 2/3 (real fixtures generated from the actual TB/wandb writers).
- "training/eval never auto-fired" → Task 10 hard constraints (multiple restatements).
- import-safety (heavy deps deferred) → Task 9.

**2. Placeholder scan:** No "TBD/TODO/handle edge cases" — every code step shows full code. The TB-writer fallback in Task 1 Step 2 gives BOTH concrete code paths and says which to verify first (not a placeholder — a documented decision point with both implementations present).

**3. Type consistency:** `IngestResult(summary, series, meta)` used consistently. Adapters fill `series` (curves) + empty `summary` everywhere. `promote_plots(scratch_plots_dir, dest_plots_dir, referenced)` signature identical in Task 6 def, Task 6 export, Task 8 call. `load_profile(root)` returns `omx_paths.Profile` (Task 5) consumed by `OmxPaths(profile=)` (Task 5 test, Task 10). `_ingest(path, fmt)` extended with `npz` branch (Task 7) used by `omx plot`. CLI verbs `plot`/`promote-plots` arg names (`--session-id`/`--output-root`/`--run-id`/`--analysis-id`/`--referenced`) consistent between Task 7/8 impl and tests.

**Gaps found & closed:** `omx plot --format npz` needed an npz→IngestResult branch (added in Task 7 Step 3). `load_profile` must skip the bootstrap-only `pending_approval` rule for approved profiles (handled in Task 5 Step 3).
