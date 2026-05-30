# OMX build #3 — `exp-init` Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first OMX skill, `exp-init` — a "research /init" that runs an interactive ambiguity-gated Socratic interview and bootstraps the user profile (`.omx/profile/{evaluator.sh, metrics.yaml, rules.md, launch.sh}`) via a new Claude-free `omx init` core verb.

**Architecture:** Two layers, per design D2/D8/H3. (1) **Claude-free core** — a new `omx_core/profile.py` module + `omx init` CLI verb that validates the `metrics.yaml` schema, writes the four profile files atomically (via the existing `atomic_path`), and seeds `evaluator.sh` from a committed reference (`reference/<name>/evaluator.sh`). This is unit-tested with zero Claude/Isaac/network dependency. (2) **Claude skill** — `skills/exp-init/SKILL.md` orchestrates the interactive interview (re-implementing deep-interview's 3-dimension ambiguity gate with an experiment-domain question topology), then shells `omx init` to persist the profile and labels it `pending approval`. The skill writes nothing to the profile directly — all profile IO and validation lives in the tested Python core, so the D8 "enforced by code, not agent goodwill" discipline holds.

**Tech Stack:** Python 3.12 (stdlib + `pyyaml` already in deps), pytest 9.x, argparse CLI, Claude Code SKILL.md (markdown). Reuses existing `omx_core.omx_paths` (`OmxPaths`, `atomic_path`, `Profile`, `validate_token`, `OmxError`/`OmxPathError`, `reference_evaluator`) and the `state.py` atomic-IO pattern.

---

## Decisions locked before this plan (do not re-litigate)

These were settled this session against the design doc; later tasks depend on them:

- **D-A (profile-write location): core `omx init` verb.** Profile schema validation + atomic write + reference-evaluator copy live in tested Python (`profile.py`), NOT in SKILL.md `Write` calls. Rationale: design §10 mandates D8 discipline be "enforced by code (not agent goodwill)"; the building blocks (`atomic_path`, `Profile`, `reference_evaluator`, `profile_file`) already exist in core. D5's "don't hardcode a verified answer" applies to the *score formula value*, not to the *validation/atomic mechanism* (a universal discipline that belongs in code).
- **D-B (interview input): prose numbered options.** `AskUserQuestion` is confirmed broken in the target environment (guard hook path stale). The interview presents ONE question per round as prose + numbered options + an explicit "or describe directly" affordance, and the user replies by number or free text. This is also the more portable 1st-class interaction model for a public-distributed skill (deep-interview's own fallback recommendation).
- **D-C (no auto-launch): exp-init runs NOTHING.** It only writes profile files and labels them `pending approval` (D4/B8). It never invokes training, eval, or any mutation skill. The four files are *templates the user later approves/edits*; `launch.sh` and `evaluator.sh` are written non-executable-by-default in spirit (no chmod +x, no execution).
- **D-D (public-repo hygiene): no machine-specific content.** No absolute paths, no private repo names, no usernames baked into `profile.py`, the reference, or SKILL.md. Use placeholders (`<your_eval_entrypoint>`, `<output_root>`, `$OMX_PROJECT_DIR`). The reference `evaluator.sh` already follows this — match it.

---

## Profile file schemas (locked here — referenced by Tasks 2/3/8)

The `omx init` verb writes exactly these four files into `.omx/profile/` (the only names `omx_paths.profile_file()` allows). Schemas:

### `metrics.yaml` (structured — the only file with a validated schema)
```yaml
# OMX profile — metrics vocabulary + output root. Consumed by omx_paths.Profile
# (vocabulary tier) and by exp-analyze (#4). Edit then remove the pending_approval line.
pending_approval: true        # exp-init writes true; user sets false / deletes on approval
output_root: experiments      # permanent-tree root (relative to repo, or absolute). design 10.1 default.
metrics: [ss_error, attitude, lin_vel, survival_pct]   # closed metric vocab (>=1)
views:   [trajectory, per_axis_bar, overlay]           # closed plot-view vocab (>=1)
aggs:    [by_axis, mean_std]                            # closed table-agg vocab (>=1)
sources: [eval_summary]                                # ingest-source vocab (>=1)
run_id_regex: null            # optional profile-specific run_id restriction (null = structural only)
keep_policy: pass_only        # pass_only | score_improvement  (B5)
score_formula: null           # D5 slot; null under pass_only, REQUIRED string under score_improvement
```
**Validation rules** (enforced by `profile.py:validate_metrics_schema`, loud-fail `OmxError`):
- `output_root`: required, non-empty string.
- `metrics`, `views`, `aggs`, `sources`: each required, a non-empty list of strings, every entry a valid token (`validate_token` rules: lowercase `[a-z0-9_]`, no `__`).
- `run_id_regex`: `null` or a string that compiles as a regex (delegate to `Profile.__post_init__` by constructing a `Profile`).
- `keep_policy`: must be exactly `pass_only` or `score_improvement`.
- `score_formula`: under `pass_only` may be `null`; under `score_improvement` MUST be a non-empty string (B5 coupling — score-less candidates are silently discarded otherwise).
- `pending_approval`: must be present and `true` when written by exp-init (a freshly-bootstrapped profile is always pending).

### `evaluator.sh` (copied from the committed reference, not generated)
Seeded by copying `reference/<profile_name>/evaluator.sh` (via `OmxPaths.reference_evaluator`). The reference ships `keep_policy=pass_only` and an honest documented stub. exp-init does NOT rewrite it; the user edits the STUB block later. `profile_name` defaults to `isaaclab` (the only shipped reference).

### `rules.md` (free-form analysis discipline)
A markdown template with headed sections the user fills:
```markdown
# Analysis discipline (consumed as guidance by exp-analyze)

## Always
- (e.g.) Report CV = std/mean for every metric; mean alone is half the picture.

## Never
- (e.g.) Assert "heavy-tail" without analyze.py-style per-env peak counting.

## Notes
- (free form)
```

### `launch.sh` (free-form training command template — never executed by exp-init)
```bash
#!/usr/bin/env bash
# OMX profile — training launch recipe. exp-loop (#6) QUEUES this as a
# 'pending approval' artifact; it is NEVER auto-fired (design D4/B8).
# Fill in your training command + GPU gate, then the human launches it.
set -euo pipefail

# GPU gate (example — adapt to your setup):
#   nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits

# Training command (placeholder — substitute your entrypoint; nothing machine-specific):
#   cd "$OMX_PROJECT_DIR" && python <your_train_entrypoint> --task "$OMX_TASK" ...
echo "launch.sh is a template; fill in your training command. exp-init never runs it."
```

---

## File Structure

- **Create** `omx-core/omx_core/profile.py` — `validate_metrics_schema`, `RULES_TEMPLATE`/`LAUNCH_TEMPLATE`/`METRICS_TEMPLATE` constants, `bootstrap_profile(paths, *, profile_name, metrics, force)`.
- **Create** `omx-core/tests/test_profile.py` — unit tests for schema validation + bootstrap (atomic, reference copy, idempotency/force).
- **Modify** `omx-core/omx_core/cli.py` — add `omx init` subcommand wiring `bootstrap_profile`.
- **Create** `omx-core/tests/test_cli_init.py` — CLI-level tests for `omx init`.
- **Create** `skills/exp-init/SKILL.md` — the interactive interview skill.
- **Modify** `.claude-plugin/plugin.json` — register `"./skills/exp-init/"` in `skills`.

Each task below is self-contained and committable. Run all `pytest`/`python3` from `omx-core/` unless noted. **Always use `python3` (the bare `python` is an Isaac wrapper).** `pip install -e .` needs `--break-system-packages` (PEP 668).

---

### Task 1: `profile.py` — metrics.yaml schema validator

**Files:**
- Create: `omx-core/omx_core/profile.py`
- Test: `omx-core/tests/test_profile.py`

- [ ] **Step 1: Write the failing tests**

Create `omx-core/tests/test_profile.py`:

```python
"""Tests for omx_core.profile — Claude-free profile bootstrap (build #3)."""
import pytest

from omx_core.omx_paths import OmxError
from omx_core.profile import validate_metrics_schema


def _good():
    return {
        "pending_approval": True,
        "output_root": "experiments",
        "metrics": ["ss_error", "attitude"],
        "views": ["trajectory"],
        "aggs": ["by_axis"],
        "sources": ["eval_summary"],
        "run_id_regex": None,
        "keep_policy": "pass_only",
        "score_formula": None,
    }


def test_valid_minimal_schema_passes():
    # returns the validated dict unchanged (echo-through, loud-fail otherwise)
    assert validate_metrics_schema(_good()) == _good()


def test_missing_output_root_raises():
    d = _good(); del d["output_root"]
    with pytest.raises(OmxError, match="output_root"):
        validate_metrics_schema(d)


def test_empty_metrics_list_raises():
    d = _good(); d["metrics"] = []
    with pytest.raises(OmxError, match="metrics"):
        validate_metrics_schema(d)


def test_metric_with_double_underscore_raises():
    # validate_token forbids '__' (it is the field separator in filenames)
    d = _good(); d["metrics"] = ["ss__error"]
    with pytest.raises(OmxError, match="metric"):
        validate_metrics_schema(d)


def test_uppercase_view_token_raises():
    d = _good(); d["views"] = ["Trajectory"]
    with pytest.raises(OmxError, match="view"):
        validate_metrics_schema(d)


def test_bad_keep_policy_raises():
    d = _good(); d["keep_policy"] = "always_keep"
    with pytest.raises(OmxError, match="keep_policy"):
        validate_metrics_schema(d)


def test_score_improvement_requires_formula():
    d = _good(); d["keep_policy"] = "score_improvement"; d["score_formula"] = None
    with pytest.raises(OmxError, match="score_formula"):
        validate_metrics_schema(d)


def test_score_improvement_with_formula_passes():
    d = _good(); d["keep_policy"] = "score_improvement"
    d["score_formula"] = "mean(ss_error) + 0.5 * cv(ss_error)"
    assert validate_metrics_schema(d)["score_formula"].startswith("mean")


def test_bad_run_id_regex_raises():
    d = _good(); d["run_id_regex"] = "([unclosed"
    with pytest.raises(OmxError, match="run_id_regex"):
        validate_metrics_schema(d)


def test_good_run_id_regex_passes():
    d = _good(); d["run_id_regex"] = r"\d{6}_.*"
    assert validate_metrics_schema(d)["run_id_regex"] == r"\d{6}_.*"


def test_pending_approval_must_be_true_when_bootstrapping():
    d = _good(); d["pending_approval"] = False
    with pytest.raises(OmxError, match="pending_approval"):
        validate_metrics_schema(d)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd omx-core && python3 -m pytest tests/test_profile.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'omx_core.profile'` (or ImportError on `validate_metrics_schema`).

- [ ] **Step 3: Write the minimal validator**

Create `omx-core/omx_core/profile.py`:

```python
"""omx_core.profile — Claude-free profile bootstrap (build #3).

exp-init (the Claude skill) runs the interview, then shells `omx init` which calls
bootstrap_profile() here. ALL profile schema validation + atomic file writes live
in this tested module (design D8: discipline enforced by code, not agent goodwill).
The skill writes nothing to .omx/profile/ directly.
"""
from __future__ import annotations

from omx_core.omx_paths import OmxError, Profile, validate_token

_KEEP_POLICIES = frozenset({"pass_only", "score_improvement"})
_VOCAB_FIELDS = ("metrics", "views", "aggs", "sources")


def validate_metrics_schema(data: dict) -> dict:
    """Validate a metrics.yaml dict (loud-fail OmxError); return it unchanged on success.

    Enforces the schema locked in the build-#3 plan: output_root present;
    metrics/views/aggs/sources are non-empty token lists; run_id_regex null-or-
    compilable; keep_policy in {pass_only, score_improvement}; score_formula
    required under score_improvement (B5); pending_approval must be True when a
    profile is bootstrapped.
    """
    if not isinstance(data, dict):
        raise OmxError(f"metrics.yaml must parse to a mapping, got {type(data).__name__}")

    out_root = data.get("output_root")
    if not isinstance(out_root, str) or out_root == "":
        raise OmxError("metrics.yaml: output_root must be a non-empty string")

    for field in _VOCAB_FIELDS:
        seq = data.get(field)
        if not isinstance(seq, list) or len(seq) == 0:
            raise OmxError(f"metrics.yaml: {field} must be a non-empty list")
        for item in seq:
            # validate_token loud-fails on non-token (uppercase, '__', separators)
            validate_token(item, f"{field} entry")

    regex = data.get("run_id_regex", None)
    if regex is not None:
        # Construct a Profile so a bad pattern fails loud HERE (post_init compiles it).
        Profile(run_id_regex=regex)

    policy = data.get("keep_policy")
    if policy not in _KEEP_POLICIES:
        raise OmxError(
            f"metrics.yaml: keep_policy must be one of {sorted(_KEEP_POLICIES)}, got {policy!r}")

    formula = data.get("score_formula", None)
    if policy == "score_improvement" and (not isinstance(formula, str) or formula == ""):
        raise OmxError(
            "metrics.yaml: score_formula is required (non-empty string) under "
            "keep_policy=score_improvement (B5: score-less candidates are discarded)")

    if data.get("pending_approval") is not True:
        raise OmxError(
            "metrics.yaml: pending_approval must be true on a freshly bootstrapped profile")

    return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd omx-core && python3 -m pytest tests/test_profile.py -q`
Expected: PASS — 11 passed.

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/omx_core/profile.py omx-core/tests/test_profile.py
git commit -m "$(cat <<'EOF'
feat(profile): metrics.yaml schema validator (build #3 task 1)

Claude-free loud-fail validator for the exp-init profile. Enforces the
locked metrics.yaml schema: token vocab lists, keep_policy enum,
score_formula required under score_improvement (B5), pending_approval gate.
Reuses omx_paths.validate_token + Profile(run_id_regex) for regex compile.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `profile.py` — file templates + `bootstrap_profile`

**Files:**
- Modify: `omx-core/omx_core/profile.py`
- Test: `omx-core/tests/test_profile.py`

- [ ] **Step 1: Write the failing tests**

Append to `omx-core/tests/test_profile.py`:

```python
import yaml

from omx_core.omx_paths import OmxPaths
from omx_core.profile import bootstrap_profile


def _bootstrap(tmp_path, **kw):
    paths = OmxPaths(root=tmp_path)
    metrics = kw.pop("metrics", _good())
    return paths, bootstrap_profile(paths, profile_name="isaaclab", metrics=metrics, **kw)


def test_bootstrap_writes_all_four_files(tmp_path):
    paths, written = _bootstrap(tmp_path)
    for name in ("evaluator.sh", "metrics.yaml", "rules.md", "launch.sh"):
        assert paths.profile_file(name).exists(), f"{name} not written"
    # bootstrap returns the list of written Paths for the CLI to print
    assert {p.name for p in written} == {"evaluator.sh", "metrics.yaml", "rules.md", "launch.sh"}


def test_bootstrap_metrics_yaml_roundtrips_and_is_valid(tmp_path):
    paths, _ = _bootstrap(tmp_path)
    loaded = yaml.safe_load(paths.profile_file("metrics.yaml").read_text())
    assert loaded["pending_approval"] is True
    assert loaded["metrics"] == _good()["metrics"]
    # the written yaml must itself pass the schema validator
    validate_metrics_schema(loaded)


def test_bootstrap_evaluator_copied_from_reference(tmp_path):
    paths, _ = _bootstrap(tmp_path)
    written = paths.profile_file("evaluator.sh").read_text()
    reference = paths.reference_evaluator("isaaclab").read_text()
    assert written == reference


def test_bootstrap_invalid_metrics_writes_nothing(tmp_path):
    bad = _good(); bad["keep_policy"] = "nope"
    paths = OmxPaths(root=tmp_path)
    with pytest.raises(OmxError, match="keep_policy"):
        bootstrap_profile(paths, profile_name="isaaclab", metrics=bad)
    # loud-fail BEFORE any write — no partial profile dir
    assert not paths.profile_file("metrics.yaml").exists()
    assert not paths.profile_dir.exists() or list(paths.profile_dir.iterdir()) == []


def test_bootstrap_refuses_overwrite_without_force(tmp_path):
    paths, _ = _bootstrap(tmp_path)
    with pytest.raises(OmxError, match="already exists"):
        bootstrap_profile(paths, profile_name="isaaclab", metrics=_good(), force=False)


def test_bootstrap_force_overwrites(tmp_path):
    paths, _ = _bootstrap(tmp_path)
    m2 = _good(); m2["metrics"] = ["only_one"]
    bootstrap_profile(paths, profile_name="isaaclab", metrics=m2, force=True)
    loaded = yaml.safe_load(paths.profile_file("metrics.yaml").read_text())
    assert loaded["metrics"] == ["only_one"]


def test_bootstrap_unknown_reference_raises(tmp_path):
    paths = OmxPaths(root=tmp_path)
    with pytest.raises(OmxError):  # reference_evaluator loud-fails on missing profile
        bootstrap_profile(paths, profile_name="nonexistent", metrics=_good())


def test_rules_and_launch_are_nonempty_templates(tmp_path):
    paths, _ = _bootstrap(tmp_path)
    assert "Analysis discipline" in paths.profile_file("rules.md").read_text()
    launch = paths.profile_file("launch.sh").read_text()
    assert launch.startswith("#!/usr/bin/env bash")
    assert "never auto-fired" in launch.lower() or "never runs it" in launch.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd omx-core && python3 -m pytest tests/test_profile.py -q`
Expected: FAIL — `ImportError: cannot import name 'bootstrap_profile'`.

- [ ] **Step 3: Write templates + `bootstrap_profile`**

Append to `omx-core/omx_core/profile.py`:

```python
import shutil

import yaml

from omx_core.omx_paths import OmxPaths, atomic_path

RULES_TEMPLATE = """\
# Analysis discipline (consumed as guidance by exp-analyze)

## Always
- (e.g.) Report CV = std/mean for every metric; mean alone is half the picture.

## Never
- (e.g.) Assert "heavy-tail" without per-env peak counting.

## Notes
- (free form)
"""

LAUNCH_TEMPLATE = """\
#!/usr/bin/env bash
# OMX profile - training launch recipe. exp-loop (#6) QUEUES this as a
# 'pending approval' artifact; it is NEVER auto-fired (design D4/B8).
# Fill in your training command + GPU gate, then the human launches it.
set -euo pipefail

# GPU gate (example - adapt to your setup):
#   nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits

# Training command (placeholder - substitute your entrypoint; nothing machine-specific):
#   cd "$OMX_PROJECT_DIR" && python <your_train_entrypoint> --task "$OMX_TASK" ...
echo "launch.sh is a template; fill in your training command. exp-init never runs it."
"""

# A non-comment-only header so PyYAML round-trips reliably; the values are the
# locked metrics.yaml schema defaults. exp-init overrides `metrics` (+ others) per interview.
_METRICS_HEADER = (
    "# OMX profile - metrics vocabulary + output root.\n"
    "# Consumed by omx_paths.Profile (vocabulary tier) and exp-analyze (#4).\n"
    "# Set pending_approval to false (or delete the key) on approval.\n"
)


def default_metrics() -> dict:
    """The locked metrics.yaml schema with placeholder vocab — the interview fills it in."""
    return {
        "pending_approval": True,
        "output_root": "experiments",
        "metrics": ["ss_error", "attitude", "lin_vel", "survival_pct"],
        "views": ["trajectory", "per_axis_bar", "overlay"],
        "aggs": ["by_axis", "mean_std"],
        "sources": ["eval_summary"],
        "run_id_regex": None,
        "keep_policy": "pass_only",
        "score_formula": None,
    }


def bootstrap_profile(paths: OmxPaths, *, profile_name: str = "isaaclab",
                      metrics: dict | None = None, force: bool = False) -> list:
    """Write the four .omx/profile/ files atomically; return the written Paths.

    Order is loud-fail-before-write: validate the schema and resolve the shipped
    reference evaluator FIRST, so an invalid profile or unknown reference leaves
    NO partial files (test_bootstrap_invalid_metrics_writes_nothing). Refuses to
    overwrite an existing profile unless force=True (a bootstrapped profile is the
    user's tuning — never silently clobbered; design 10.3 'profile is sacred').
    """
    metrics = default_metrics() if metrics is None else metrics
    validate_metrics_schema(metrics)                       # loud-fail #1 (before any write)
    reference = paths.reference_evaluator(profile_name)    # loud-fail #2 (missing reference)

    targets = {name: paths.profile_file(name)
               for name in ("evaluator.sh", "metrics.yaml", "rules.md", "launch.sh")}
    if not force:
        existing = [p for p in targets.values() if p.exists()]
        if existing:
            raise OmxError(
                f"profile already exists ({[p.name for p in existing]}); pass force=True "
                "to overwrite (profile is the user's tuning - never silently clobbered)")

    # metrics.yaml: header comment + the schema block (safe_dump, stable key order).
    metrics_text = _METRICS_HEADER + yaml.safe_dump(metrics, sort_keys=True, default_flow_style=False)

    written = []
    # evaluator.sh is a byte-copy of the committed reference (NOT generated).
    with atomic_path(targets["evaluator.sh"]) as tmp:
        shutil.copyfile(reference, tmp)
    written.append(targets["evaluator.sh"])
    for name, text in (("metrics.yaml", metrics_text),
                       ("rules.md", RULES_TEMPLATE),
                       ("launch.sh", LAUNCH_TEMPLATE)):
        with atomic_path(targets[name]) as tmp:
            tmp.write_text(text)
        written.append(targets[name])
    return written
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd omx-core && python3 -m pytest tests/test_profile.py -q`
Expected: PASS — 19 passed (11 from Task 1 + 8 new).

- [ ] **Step 5: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/omx_core/profile.py omx-core/tests/test_profile.py
git commit -m "$(cat <<'EOF'
feat(profile): bootstrap_profile writes 4 profile files atomically (build #3 task 2)

bootstrap_profile validates the schema and resolves the shipped reference
evaluator BEFORE any write (loud-fail leaves no partial profile), copies
evaluator.sh byte-for-byte from reference/<name>/, and atomic-writes
metrics.yaml/rules.md/launch.sh. Refuses overwrite without force (profile
is the user's tuning - never silently clobbered). launch.sh is a template
exp-init NEVER executes (D4/B8).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `omx init` CLI verb

**Files:**
- Modify: `omx-core/omx_core/cli.py`
- Test: `omx-core/tests/test_cli_init.py`

- [ ] **Step 1: Write the failing tests**

Create `omx-core/tests/test_cli_init.py`:

```python
"""CLI-level tests for `omx init` (build #3 task 3)."""
import json

import pytest
import yaml

from omx_core.cli import main
from omx_core.omx_paths import OmxPaths


def test_init_default_creates_profile(tmp_path, capsys):
    rc = main(["init", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["profile_name"] == "isaaclab"
    assert sorted(out["written"]) == ["evaluator.sh", "launch.sh", "metrics.yaml", "rules.md"]
    paths = OmxPaths(root=tmp_path)
    assert paths.profile_file("metrics.yaml").exists()


def test_init_accepts_metrics_json(tmp_path, capsys):
    # exp-init passes the interview-derived metrics dict as JSON on the CLI
    metrics = {
        "pending_approval": True, "output_root": "out",
        "metrics": ["a"], "views": ["v"], "aggs": ["g"], "sources": ["s"],
        "run_id_regex": None, "keep_policy": "pass_only", "score_formula": None,
    }
    rc = main(["init", "--root", str(tmp_path), "--metrics-json", json.dumps(metrics)])
    assert rc == 0
    loaded = yaml.safe_load(OmxPaths(root=tmp_path).profile_file("metrics.yaml").read_text())
    assert loaded["metrics"] == ["a"]
    assert loaded["output_root"] == "out"


def test_init_invalid_metrics_json_rc2(tmp_path, capsys):
    bad = '{"keep_policy": "nope"}'
    rc = main(["init", "--root", str(tmp_path), "--metrics-json", bad])
    assert rc == 2  # SystemExit code surfaced by main()


def test_init_refuses_overwrite_rc2(tmp_path):
    assert main(["init", "--root", str(tmp_path)]) == 0
    assert main(["init", "--root", str(tmp_path)]) == 2  # already exists -> loud-fail


def test_init_force_overwrites(tmp_path):
    assert main(["init", "--root", str(tmp_path)]) == 0
    assert main(["init", "--root", str(tmp_path), "--force"]) == 0


def test_init_unknown_reference_rc2(tmp_path):
    rc = main(["init", "--root", str(tmp_path), "--profile-name", "ghost"])
    assert rc == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd omx-core && python3 -m pytest tests/test_cli_init.py -q`
Expected: FAIL — argparse exits 2 with "invalid choice: 'init'" (subcommand not registered).

- [ ] **Step 3: Wire `omx init` into cli.py**

In `omx-core/omx_core/cli.py`, add the import near the top (after the existing `from omx_core.decision import ...` line, line 17):

```python
from omx_core.profile import bootstrap_profile, default_metrics
from omx_core.omx_paths import OmxPaths
```

Add the command handler (place it after `_cmd_eval`, before `_now_stamp`):

```python
def _cmd_init(args) -> int:
    """Bootstrap .omx/profile/ from the interview-derived metrics (Claude-free).

    The exp-init skill (#3) shells this after the interview; --metrics-json carries
    the interview result, --root anchors .omx/ (design H4). Profile schema validation
    + atomic writes live in profile.bootstrap_profile (D8: enforced by code).
    """
    if args.metrics_json is not None:
        try:
            metrics = json.loads(args.metrics_json)
        except (ValueError, TypeError) as e:
            raise SystemExit(f"--metrics-json is not valid JSON: {e}")
    else:
        metrics = default_metrics()
    paths = OmxPaths(root=args.root)
    try:
        written = bootstrap_profile(
            paths, profile_name=args.profile_name, metrics=metrics, force=args.force)
    except OmxError as e:
        raise SystemExit(str(e))
    print(json.dumps({
        "profile_name": args.profile_name,
        "root": str(paths.omx_dir),
        "written": [p.name for p in written],
        "pending_approval": True,
    }))
    return 0
```

In `build_parser()`, register the subcommand (place after the `pe` (`eval`) block, before `return p`):

```python
    pn = sub.add_parser("init", help="bootstrap .omx/profile/ from interview metrics (Claude-free)")
    pn.add_argument("--root", required=True, help="anchor dir under which .omx/ lives (design H4)")
    pn.add_argument("--profile-name", default="isaaclab", dest="profile_name",
                    help="committed reference profile to seed evaluator.sh from")
    pn.add_argument("--metrics-json", default=None, dest="metrics_json",
                    help="metrics.yaml content as a JSON object; omitted = built-in defaults")
    pn.add_argument("--force", action="store_true", help="overwrite an existing profile")
    pn.set_defaults(func=_cmd_init)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd omx-core && python3 -m pytest tests/test_cli_init.py -q`
Expected: PASS — 6 passed.

- [ ] **Step 5: Run the full core suite (no regressions)**

Run: `cd omx-core && python3 -m pytest tests/ -q`
Expected: PASS — prior 223 + 19 (profile) + 6 (cli_init) = 248 passed (1 skipped carried from before). Exact count may differ slightly; the bar is **zero failures** and all new tests passing.

- [ ] **Step 6: Commit**

```bash
cd /workspace/oh-my-experiments
git add omx-core/omx_core/cli.py omx-core/tests/test_cli_init.py
git commit -m "$(cat <<'EOF'
feat(cli): add `omx init` verb to bootstrap the profile (build #3 task 3)

exp-init shells `omx init --root <anchor> --metrics-json <interview-result>`
to persist .omx/profile/. Verb is a thin entry over profile.bootstrap_profile
(all validation/atomic-write in the tested core). rc 0 on success, rc 2 on
loud-fail (bad json, schema violation, existing profile, unknown reference).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Manual end-to-end smoke of `omx init`

**Files:** none (verification task — proves the installed CLI works, not just pytest).

- [ ] **Step 1: Reinstall editable + smoke the happy path**

Run:
```bash
cd /workspace/oh-my-experiments/omx-core
pip install -e . --break-system-packages -q
cd /tmp && rm -rf omx-smoke && mkdir omx-smoke && cd omx-smoke
omx init --root . 
```
Expected stdout: a JSON line like
`{"profile_name": "isaaclab", "root": "/tmp/omx-smoke/.omx", "written": ["evaluator.sh", "metrics.yaml", "rules.md", "launch.sh"], "pending_approval": true}`

- [ ] **Step 2: Verify the files + that metrics.yaml re-validates**

Run:
```bash
cd /tmp/omx-smoke
ls -la .omx/profile/
python3 -c "import yaml,sys; from omx_core.profile import validate_metrics_schema; validate_metrics_schema(yaml.safe_load(open('.omx/profile/metrics.yaml'))); print('metrics.yaml VALID')"
diff .omx/profile/evaluator.sh "$(python3 -c 'from omx_core.omx_paths import OmxPaths; print(OmxPaths(root=".").reference_evaluator("isaaclab"))')" && echo "evaluator.sh == reference"
```
Expected: four files listed; `metrics.yaml VALID`; `evaluator.sh == reference`.

- [ ] **Step 3: Smoke the loud-fail paths**

Run:
```bash
cd /tmp/omx-smoke
omx init --root . ; echo "rc=$?"          # already exists -> rc=2
omx init --root . --force ; echo "rc=$?"  # rc=0
omx init --root /tmp/omx-smoke2 --metrics-json '{"keep_policy":"x"}' ; echo "rc=$?"  # rc=2
```
Expected: first `rc=2` (with "already exists" message), second `rc=0`, third `rc=2` (schema error message).

- [ ] **Step 4: Clean up the smoke dir**

Run: `rm -rf /tmp/omx-smoke /tmp/omx-smoke2`
Expected: removed. (No commit — verification only.)

---

### Task 5: `exp-init` SKILL.md — frontmatter + overview + interview gate

**Files:**
- Create: `skills/exp-init/SKILL.md`

> This task and Task 6 build one file. Split for review granularity: Task 5 = the interview machinery (frontmatter, gate formula, question topology, prose-option protocol); Task 6 = the persistence handoff (`omx init` call, profile presentation, pending-approval gate). Commit after each.

- [ ] **Step 1: Write the skill frontmatter + overview + interview machinery**

Create `skills/exp-init/SKILL.md`:

````markdown
---
name: exp-init
description: Bootstrap the OMX experiment profile via an interactive ambiguity-gated Socratic interview. Use when setting up experiment-analysis infrastructure for a research project (the "research /init") — elicits the optimization objective, eval method, success criteria, metric vocabulary, and launch recipe, then writes .omx/profile/{evaluator.sh, metrics.yaml, rules.md, launch.sh} marked pending approval. Triggers on "set up experiment analysis", "exp-init", "실험 분석 셋업", "프로파일 만들어".
argument-hint: "[--profile-name <name>] [--root <dir>] <one-line research description>"
---

# exp-init — bootstrap the OMX experiment profile

## Overview

`exp-init` is OMX's "research /init". It runs an **interactive** Socratic interview to
elicit how *this* researcher's experiments should be analyzed, then bootstraps the user
profile that every other OMX skill (exp-analyze/design/loop) reads.

**It writes profile files and NOTHING else.** It never launches training, never runs eval,
never edits source. The four files it produces are labelled `pending approval` — templates
the user reviews and edits before any OMX run consumes them (design D4/B8 — training
launch is never auto-fired).

**Announce at start:** "Using exp-init to interview you and bootstrap the OMX profile."

## What it produces (via the `omx init` core verb — not direct file writes)

`.omx/profile/` (anchored at the cwd or the chosen `--root`, resolved BEFORE output_root — design H4):
- `metrics.yaml` — output_root + metric/view/agg/source vocabulary + keep_policy + score_formula slot
- `evaluator.sh` — seeded from the committed reference (`reference/<profile-name>/evaluator.sh`); user edits the stub later
- `rules.md` — the user's analysis discipline ("CV mandatory", etc.)
- `launch.sh` — the training-command template (NEVER executed here)

All schema validation + atomic writes happen in the tested Python core (`omx init`), not in
this skill — so the structure discipline is enforced by code, not by this skill's diligence.

## The ambiguity gate (re-implemented from deep-interview — pattern, not import)

OMX reuses deep-interview's proven 3-dimension weighted gate. **Do not invent a new
5-dimension vector** — map the 5 experiment topics onto the 3 dimensions:

| Dimension (weight) | exp-init topics folded in | What "clear" means |
|:--|:--|:--|
| **Goal (0.40)** | objective | One quantity + direction stated without qualifiers |
| **Criteria (0.30)** | eval-method + success-criteria + score-formula | A command produces the verdict AND a numeric threshold defines success |
| **Constraints (0.30)** | metrics (axes/vocab) + launch-recipe (GPU/command) | The metric axes are enumerated AND the exact training command + GPU gate are stated |

**Ambiguity formula (greenfield):**
```
ambiguity = 1 − (goal·0.40 + criteria·0.30 + constraints·0.30)
```
Each clarity score is in `[0.0, 1.0]`. **Threshold = 0.2** (proceed to profile-write when
`ambiguity ≤ 0.2`). Soft warning at round 10; hard cap at round 20 ("proceeding with current
clarity"). The user may exit early from round 3+ ("enough", "build it", "go").

## Interview loop (ONE question per round — interactive, human answers every round)

This is the interactive part (H2) — NOT autonomous. Loop until `ambiguity ≤ 0.2` OR early exit:

1. **Score the three dimensions** from what's known so far (start all at ~0.0, or higher if the
   initial description already pins a dimension). Compute `ambiguity`.
2. **Target the weakest dimension.** Generate ONE question that most reduces its ambiguity.
   Use the sample gating questions:
   - Goal: "What single quantity should the next experiment move, and in which direction?"
   - Criteria: "What command produces the pass/fail verdict, and what numeric threshold = success?"
   - Criteria (score-formula, D5): surface any existing run data — "Your past runs show
     ss_error mean X with CV Y; should success aggregate by mean, mean+λ·CV, or per-axis
     worst-case?" (only ask if keep_policy will be score_improvement).
   - Constraints: "Which metric axes matter (give the closed list), and what is the exact
     training command + GPU gate?"
3. **Ask using the prose-option protocol** (see below). Wait for the human's answer.
4. **Re-score** the targeted dimension from the answer; recompute `ambiguity`.
5. **Report progress** in one line: `Round {n} | targeting {dim} | ambiguity {pct}%` then the question.
6. Repeat.

### Prose-option protocol (AskUserQuestion is NOT used)

This skill does **not** call `AskUserQuestion` (it presents questions as prose for portability).
Each round, present:

```
Round {n} | {dimension} | ambiguity {pct}%
{the question}

  [1] {concrete option A}
  [2] {concrete option B}
  [3] (other — describe in your own words)
```

The user replies with a number or free text. Offer concrete options drawn from any existing
data you can read (see "Grounding in existing data" below), but always allow free text — never
force a choice. If the answer is itself ambiguous, that dimension's clarity stays low and you
ask a sharper follow-up next round.

### Grounding in existing data (optional, strengthens the Criteria dimension)

Before/while interviewing, you MAY read existing experiment data to offer concrete options and
to ground the score-formula question — using ONLY the Claude-free core verbs (never invent paths):
- `omx ingest --path <eval summary.json> --format eval_summary` — see what metrics/axes exist.
- `omx reduce summarize --path <...> --format eval_summary --cv-field <metric>` — get mean/std/CV
  to inform the mean-vs-CV-vs-worst-case score-formula choice (D5).

This is read-only grounding; it writes nothing. If no data exists yet, proceed with the
interview on the user's stated intent alone.
````

- [ ] **Step 2: Verify the file reads cleanly + frontmatter parses**

Run:
```bash
cd /workspace/oh-my-experiments
python3 -c "import yaml; t=open('skills/exp-init/SKILL.md').read(); fm=t.split('---')[1]; d=yaml.safe_load(fm); assert d['name']=='exp-init'; assert 'description' in d; print('frontmatter OK:', list(d))"
```
Expected: `frontmatter OK: ['name', 'description', 'argument-hint']`

- [ ] **Step 3: Commit**

```bash
cd /workspace/oh-my-experiments
git add skills/exp-init/SKILL.md
git commit -m "$(cat <<'EOF'
feat(exp-init): interview machinery (frontmatter + ambiguity gate) (build #3 task 5)

First OMX skill. Re-implements deep-interview's 3-dimension weighted gate
(Goal 0.40 / Criteria 0.30 / Constraints 0.30, threshold 0.2), maps the 5
experiment topics onto those 3 dims (design 4.1), and uses a prose numbered-
option protocol instead of AskUserQuestion (portability). Read-only data
grounding via omx ingest/reduce. No file writes yet (task 6).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: `exp-init` SKILL.md — persistence handoff + pending-approval gate

**Files:**
- Modify: `skills/exp-init/SKILL.md`

- [ ] **Step 1: Append the persistence + approval sections**

Append to `skills/exp-init/SKILL.md`:

````markdown
## When the gate clears (`ambiguity ≤ 0.2` or early exit): build the profile

Do NOT write profile files yourself. Assemble the interview result into a `metrics.yaml`
dict and shell the Claude-free core verb, which validates and atomic-writes it:

1. **Assemble the metrics dict** from the interview (these keys match the locked schema):
   ```json
   {
     "pending_approval": true,
     "output_root": "<the permanent-tree root the user chose; default 'experiments'>",
     "metrics": ["<closed metric vocab from the Constraints dimension>"],
     "views": ["trajectory", "per_axis_bar", "overlay"],
     "aggs": ["by_axis", "mean_std"],
     "sources": ["eval_summary"],
     "run_id_regex": null,
     "keep_policy": "<pass_only | score_improvement — from the Criteria dimension>",
     "score_formula": "<null under pass_only; the elicited formula string under score_improvement>"
   }
   ```
   Every list entry must be a lowercase token (`[a-z0-9_]`, no `__`); the core will loud-fail
   otherwise (and you should re-ask rather than mangle the user's word).

2. **Resolve the anchor root (H4).** Default to the cwd. If the user gave `--root`, use it.
   `.omx/` lives at this anchor, independent of `output_root` (which is stored *inside*
   metrics.yaml and may point elsewhere).

3. **Shell `omx init`** with the assembled dict as JSON:
   ```bash
   omx init --root "<anchor>" --profile-name "<profile-name, default isaaclab>" \
       --metrics-json '<the JSON dict from step 1>'
   ```
   - rc 0 → it prints `{"written": [...], "pending_approval": true, ...}`.
   - rc 2 → it loud-failed (schema violation, existing profile, unknown reference). Read the
     message: on "already exists", ask the user whether to re-run with `--force` (never pass
     `--force` without asking — the existing profile is their tuning). On a schema error, fix
     the offending field WITH the user and retry.

## Present the profile + the pending-approval gate (this is the stopping point)

After a successful `omx init`, present the four files for review and STOP. Do not proceed to
any analysis, design, eval, or training:

```
Profile bootstrapped (pending approval) at <anchor>/.omx/profile/:
  - metrics.yaml   — <one-line summary: output_root, N metrics, keep_policy>
  - evaluator.sh   — seeded from the <profile-name> reference (edit the STUB block for your eval)
  - rules.md       — your analysis discipline (fill in Always/Never)
  - launch.sh      — your training command template (exp-init never runs it)

Next steps (yours, not mine):
  1. Edit evaluator.sh — replace the STUB with your real eval command.
  2. Fill rules.md + launch.sh.
  3. Set pending_approval: false in metrics.yaml (or delete the key) to approve.
Once approved, run exp-analyze on your runs.
```

**Hard gate (mirrors deep-interview's approval gate):** until the user explicitly approves
(edits `pending_approval` to false, or says so), `exp-init` MUST NOT invoke exp-analyze,
exp-design, exp-loop, or any mutation/execution skill, and MUST NOT run training or eval. The
profile is a *proposal*. This honors the repo rule "훈련 종료/시작은 유저가 직접" with no
override path in v0.1.

## Re-running exp-init

If a profile already exists, `omx init` refuses (rc 2). exp-init then asks whether to
overwrite (`--force`) — overwriting replaces the user's tuning, so it is always an explicit,
confirmed choice, never automatic.
````

- [ ] **Step 2: Verify the whole skill is internally consistent**

Run:
```bash
cd /workspace/oh-my-experiments
grep -n "omx init" skills/exp-init/SKILL.md
grep -n "AskUserQuestion" skills/exp-init/SKILL.md && echo "FAIL: should NOT mention AskUserQuestion as used" || echo "OK: no AskUserQuestion usage"
grep -c "pending approval\|pending_approval" skills/exp-init/SKILL.md
```
Expected: `omx init` appears (in the shell-call section); the AskUserQuestion grep finds only the "is NOT used" line (acceptable — it's a negation) OR nothing; `pending` count ≥ 4. Manually confirm: the only `AskUserQuestion` mentions are negations ("is NOT used", "AskUserQuestion is NOT used").

- [ ] **Step 3: Commit**

```bash
cd /workspace/oh-my-experiments
git add skills/exp-init/SKILL.md
git commit -m "$(cat <<'EOF'
feat(exp-init): persistence handoff + pending-approval gate (build #3 task 6)

When the ambiguity gate clears, exp-init assembles the interview result into a
metrics.yaml dict and shells `omx init` (validation/atomic-write in tested
core). Presents the 4 profile files for review and STOPS — hard gate: no
analysis/design/eval/training until the user approves (sets pending_approval
false). Honors "훈련 시작/종료는 유저" with no override (D4/B8).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Register `exp-init` in plugin.json

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Read the current skills field**

Run: `cd /workspace/oh-my-experiments && python3 -c "import json; d=json.load(open('.claude-plugin/plugin.json')); print('skills =', d['skills'])"`
Expected: `skills = []`

- [ ] **Step 2: Add the exp-init entry**

Edit `.claude-plugin/plugin.json` — change the `skills` line from:
```json
  "skills": []
```
to:
```json
  "skills": [
    "./skills/exp-init/"
  ]
```

- [ ] **Step 3: Verify plugin.json still parses + lists exp-init**

Run:
```bash
cd /workspace/oh-my-experiments
python3 -c "import json; d=json.load(open('.claude-plugin/plugin.json')); assert d['skills']==['./skills/exp-init/'], d['skills']; assert d['name']=='oh-my-experiments'; print('plugin.json OK:', d['skills'])"
```
Expected: `plugin.json OK: ['./skills/exp-init/']`

- [ ] **Step 4: Commit**

```bash
cd /workspace/oh-my-experiments
git add .claude-plugin/plugin.json
git commit -m "$(cat <<'EOF'
feat(plugin): register exp-init skill in plugin.json (build #3 task 7)

First entry in the skills array. The omha card (cards/omx.json) already lists
exp-init in triggers.skills; this makes it discoverable as an installed skill.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Final integration verification + docs update

**Files:**
- Modify: `docs/HANDOFF.md` (status line for #3)

- [ ] **Step 1: Run the full core test suite one final time**

Run: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/ -q`
Expected: zero failures; the new profile (19) + cli_init (6) tests all pass; prior suite intact.

- [ ] **Step 2: Confirm the skill + CLI + plugin wiring agree**

Run:
```bash
cd /workspace/oh-my-experiments
# the skill references exactly the verb the CLI provides:
omx init --help 2>&1 | grep -q -- "--metrics-json" && echo "CLI has --metrics-json: OK"
# the plugin registers the skill dir that exists:
test -f skills/exp-init/SKILL.md && python3 -c "import json; assert './skills/exp-init/' in json.load(open('.claude-plugin/plugin.json'))['skills']" && echo "plugin<->skill wiring: OK"
# the card already expects this skill name (no edit needed, just confirm):
python3 -c "import json; c=json.load(open('cards/omx.json')); assert 'exp-init' in c['triggers']['skills']; print('card lists exp-init: OK')" 2>/dev/null || echo "NOTE: cards/omx.json not in this repo path — skip if card lives in heroacademia"
```
Expected: `CLI has --metrics-json: OK`, `plugin<->skill wiring: OK`, and the card line (or the skip NOTE if the card lives in the heroacademia repo, not here).

- [ ] **Step 3: Update HANDOFF.md status**

In `docs/HANDOFF.md`, update the build-order status to mark #3 done. Find the "다음에 할 일" / DAG section and change the #3 line to reflect completion, e.g. append after the existing #3 mention:
```markdown
- **#3 exp-init — DONE** (this session). `omx_core/profile.py` (validate_metrics_schema + bootstrap_profile) + `omx init` verb + `skills/exp-init/SKILL.md` (3-dim ambiguity gate, prose options, omx-init handoff, pending-approval hard gate) + plugin.json registration. Core suite green. NEXT = #4 exp-analyze (PNG-vision, WandB/TB adapters).
```

- [ ] **Step 4: Commit the docs update**

```bash
cd /workspace/oh-my-experiments
git add docs/HANDOFF.md
git commit -m "$(cat <<'EOF'
docs: mark build #3 (exp-init) done in HANDOFF (build #3 task 8)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Final branch summary (no push — user-gated)**

Run: `cd /workspace/oh-my-experiments && git log --oneline -8 && git status -s`
Expected: 7 new commits (tasks 1,2,3,5,6,7,8), working tree clean. **Do NOT push** — pushing is user-gated (commit auto, push on explicit request only).

---

## Self-Review (against design §4 / §4.1 / §8 #3 / §10)

**Spec coverage:**
- §4.1 3-dimension mapping (Goal/Criteria/Constraints with the 5 topics folded in) → Task 5 table ✓
- §4.1 ambiguity formula + threshold 0.2 + interactive (H2) → Task 5 ✓
- §4 output = `.omx/profile/{evaluator.sh, metrics.yaml, rules.md, launch.sh}` `pending approval` → Tasks 2/3/6 ✓
- §8 #3 "bootstraps profile; resolves .omx root + output_root bootstrap (H4)" → metrics.yaml carries output_root; `--root` anchors .omx (Tasks 2/3/5/6) ✓
- §10.1 H4 (.omx at fixed anchor, output_root stored inside) → `OmxPaths(root=...)` + output_root in metrics.yaml ✓
- B5 (score required under score_improvement) → `validate_metrics_schema` Task 1 + score-formula interview question Task 5 ✓
- D4/B8 (no auto-launch) → launch.sh is a non-executed template; hard gate Task 6 ✓
- D5 (score formula = profile slot, elicited) → score_formula slot + Criteria-dim question Task 5 ✓
- D8 (discipline enforced by code) → all validation/atomic-write in profile.py, skill never writes directly ✓
- AskUserQuestion broken → prose-option protocol Task 5 ✓
- Public-repo hygiene → placeholders only; reference reused, not regenerated ✓

**Placeholder scan:** No "TODO"/"implement later" in steps; every code/edit step shows full content. The *profile templates themselves* contain illustrative placeholders (`<your_eval_entrypoint>`) by design — those are the user-fill slots, not plan gaps.

**Type consistency:** `validate_metrics_schema(dict)->dict`, `bootstrap_profile(paths, *, profile_name, metrics, force)->list[Path]`, `default_metrics()->dict` — names identical across Tasks 1/2/3/4. CLI flags `--root/--profile-name/--metrics-json/--force` identical across Tasks 3/4/5/6. `omx init` JSON output keys (`profile_name`, `root`, `written`, `pending_approval`) consistent Task 3↔4↔6.
