# run-completion gate — execution plan (omx 0.17.0)

Design: `../specs/2026-09-19-run-completion-gate-design.md`. Section references below
(§3, §4, …) are to that document. TDD: every task writes its failing test first.

Baseline before task 1: `cd omx-core && python -m pytest -q` must be green, and its
test count recorded — a later green with fewer tests is not a pass
(a vendor-green-by-deleting-tests guard).

---

## Task 1 — `run_completion` contract: parse + validate

**Files**: `omx-core/omx_core/profile.py`, `omx-core/tests/test_run_completion_contract.py`

Add `validate_run_completion(block: dict) -> dict` and `load_run_completion(root) -> dict | None`.

- `load_run_completion` reads `profile/metrics.yaml` via the existing
  `load_profile_metrics`, returns `None` when the `run_completion` key is absent.
- `validate_run_completion` loud-fails `OmxError` on: non-mapping; missing `runs` /
  `finished` / `required` / `how`; `runs` / `finished` / `how` not non-empty strings;
  `required` not a non-empty list of non-empty strings; `exclude` present but not a
  list of strings; any glob that is absolute or contains `..`.
- **Do not touch `validate_metrics_schema`.** It validates a *freshly bootstrapped*
  profile and requires `pending_approval: true`; a live profile gaining a
  `run_completion` block must not be forced back through it.

**Tests**: valid block round-trips unchanged; each invalid shape raises `OmxError` with
the offending key named; absent block → `None`; absolute and `..` globs rejected.

---

## Task 2 — the verdict engine

**Files**: `omx-core/omx_core/completion.py` (new), `omx-core/tests/test_completion_verdict.py`

`evaluate_completion(root) -> dict` returning
`{"state": ..., "runs": [...], "missing": [...], "output_root": str|None, "how": str|None}`
with `state` one of `no-contract | checked | incomplete | unreadable` (§4).

Algorithm:
1. `load_run_completion(root)`; `None` → `{"state": "no-contract"}`.
2. Resolve `output_root` from the same `metrics.yaml`. Not a directory, or an `OSError`
   on listing it → `{"state": "unreadable", "output_root": <the path it tried>}`.
   **This branch must never be reachable by returning zero runs instead** — it is the
   whole point of §4.
3. Run dirs = `output_root.glob(runs)` that are directories, minus anything matching
   any `exclude` glob (matched against the path relative to `output_root`).
4. A run dir is *finished* iff `next(run_dir.glob(finished), None)` is not `None`.
   **`rc` is never read.**
5. For each finished run, each `required` glob must match at least once. Collect
   misses as `{"run": <rel path>, "missing": [<globs>]}`.
6. Misses → `incomplete`; none → `checked` (including zero finished runs, which is an
   honest pass because step 2 proved the tree was readable).

`how` is returned with `{run}` substituted per entry in `missing`.

**Tests** (fixture trees under `tmp_path`, no network, no ssh):
- finished run, no artifacts → `incomplete`, missing globs and substituted `how` present
- same tree with the artifacts created → `checked`
- `exclude` keeps a smoke run out of the subject set
- unfinished run (no `finished` match) is not a subject
- `output_root` missing → `unreadable`, **not** `checked`
- readable `output_root` with zero run dirs → `checked`
- no `run_completion` → `no-contract`

---

## Task 3 — receipt + defer store

**Files**: `omx-core/omx_core/completion.py`, `omx-core/tests/test_completion_receipt.py`

Stored under the runtime layer beside the other omx state (follow
`OmxPaths`/`runtime_dir` resolution used by `compact_breadcrumb`; anchored roots use
`.hq/runtime/experiments/`, legacy roots `.omx/`). Written through `atomic_path`.

- `write_receipt(paths, verdict, *, source, now_iso)` — `{checked_at, root, state,
  runs_checked, omx_version, source}`; `source` is `"local"` or `"remote"`.
- `read_receipt(paths)` → dict or `None`; corrupt JSON → `None` (never raises).
- `receipt_satisfies(receipt, now_iso, max_age_h=12)` → bool: `state == "checked"`
  **and** `checked_at` within `max_age_h`. A non-`checked` receipt never satisfies.
- `write_defer(paths, reason, now_iso)` / `active_defer(paths, now_iso, ttl_h=12)`.
  A defer with an empty reason is refused.

**Tests**: fresh `checked` receipt satisfies; the same receipt aged past `max_age_h`
does not; an `incomplete` receipt never satisfies at any age; corrupt file → `None`,
no raise; defer expires; empty-reason defer refused.

---

## Task 4 — CLI verbs

**Files**: `omx-core/omx_core/cli.py`, `omx-core/tests/test_close_verbs.py`

Register beside the existing verbs, following the `--root` convention
(`default=None, help="optional .omx anchor; default: #13 ladder"`).

| Verb | Args | Exit |
|:--|:--|:--|
| `close-check` | `--root`, `--json`, `--record` | 0 `no-contract`/`checked`, 1 `incomplete`, 2 `unreadable` |
| `close-ack` | `--root`, `--from <path or ->` | 0 accepted, 2 refused |
| `close-defer` | `--root`, `--reason` (required, non-empty) | 0 |

- `close-check --json` prints the verdict dict on stdout; the human form prints the
  run → missing → `how` lines. `--record` writes the receipt (`source: "local"`).
- `close-ack` reads a `close-check --json` payload produced anywhere, validates its
  shape, **refuses any state other than `checked`** with the reason on stderr and
  exit 2, and otherwise stores it with `source: "remote"`.
- `close-defer` writes the dated reason.

**Tests**: each exit code on a fixture tree; `close-ack` refuses an `incomplete`
payload; `close-ack -` reads stdin; a malformed payload exits 2 rather than raising.

---

## Task 5 — `closure_guard` hook handler

**Files**: `oh-my-experiments/hooks/handlers.py`, `omx-core/tests/test_closure_guard.py`

`closure_guard(payload)` — `PreToolUse`, `tool_name == "Bash"`.

1. `shlex.split` the command; a `ValueError` → `None` (allow). **No regex over the raw
   string.**
2. Closure-declaration match on tokens (§6): `hq post` with `--category handoff`;
   `omx loop-disarm` with `--reason done`; `omx loop-mark-done` with `--reason done`.
   Handle `--reason=done` as well as `--reason done`. Anything else → `None`.
3. Compound commands: split the token stream on `&&`, `||`, `;`, `|` and test each
   segment, so `cd x && hq post --category handoff ...` is seen.
4. Active defer → `None`. Fresh satisfying receipt → `None`.
5. `evaluate_completion(root)`: `no-contract` / `checked` → `None`;
   `incomplete` / `unreadable` → deny.
6. Any exception anywhere → `None` (fail-open, the repository's D9 contract).

Deny reason: **under 1 200 characters**, names the run(s), the missing globs, the
substituted `how`, and `omx close-defer --reason "<why>"` as the escape. The
`unreadable` variant names the root and both `omx close-check --root <R> --json` and
`omx close-ack --from -`. Pinned by a test asserting the length ceiling.

**Tests**: each of the three closure commands denied on an `incomplete` fixture;
`--reason cancel` (not `done`) is not a closure declaration; a quoted argument
containing the literal text `--category handoff` inside a `--summary` does **not**
trigger; non-Bash tools pass; `unreadable` denies; `no-contract` allows; a poisoned
`omx_core` import still allows (import-safe, mirroring
`test_handlers_import_without_omx_core`); deny reason ≤ 1 200 chars.

---

## Task 6 — `completion_notice` SessionStart handler

**Files**: `hooks/handlers.py`, `omx-core/tests/test_completion_notice.py`

Fires on `startup|resume`. An omx layer present and `load_run_completion` → `None`
gives one injected line naming the `run_completion` block and the file it goes in.
A contract present, or no omx layer, injects nothing. Never raises.

**Tests**: contract absent → block present and names `run_completion`; contract
present → `None`; no omx layer → `None`; internal error → `None`.

---

## Task 7 — hook registration

**Files**: `.claude-plugin/plugin.json`, `omx-core/tests/test_hook_registration.py`

Add `closure_guard` to `PreToolUse` with matcher `Bash`, and `completion_notice` to
`SessionStart` with matcher `startup|resume` (the existing `compact` entry stays).
Register both in `HANDLERS`.

**Test**: every handler named in `plugin.json` exists in `HANDLERS` and vice versa —
this is the registration-drift check, and it must fail if either side is edited alone.

---

## Task 8 — `stage_check` Stop handler

**Files**: `hooks/handlers.py`, `omx-core/tests/test_stage_check.py`

Session-scoped (§8). Reads the transcript path from the payload.

- Walk the transcript by **turn boundary**, not by a byte tail: iterate records, treat
  a `user` record as a boundary. A user record's `content` may be a **bare string**
  as well as a list of blocks — handle both, or every boundary is lost.
- Collect every `STAGE(exp) → <token>` emitted in assistant text, and every skill
  actually opened (a `Skill` tool_use whose `skill` names an omx skill, or an
  `exp-*` skill invocation).
- Block when: a collected token is outside
  `{exp-init, exp-analyze, exp-design, exp-loop, program, wiki, tree, recipe}`; or a
  collected `exp-*` token's skill was never opened anywhere in the session.
- No STAGE line at all → `None`. Unreadable/absent transcript → `None`.
- `stop_hook_active` is honoured here (unlike `loop_gate`): this gate has nothing to
  iterate, so one block per session is enough and repeating it would trap the session.

**Tests** (synthetic `.jsonl`): out-of-vocabulary token blocks and the message lists
the allowed set; declared `exp-analyze` never opened blocks; declared and opened
passes; a user record whose `content` is a bare string still yields a boundary;
missing transcript → `None`; already-blocked (`stop_hook_active: true`) → `None`.

---

## Task 9 — repository hygiene test

**Files**: `omx-core/tests/test_no_project_content.py`

Walk the repository (excluding `.git`) and assert none of `p6`, `albc`, `IsaacLab`,
`Isaac Lab` appears, case-insensitively, in any tracked text file. Success criterion 4.

---

## Task 10 — skills and docs

**Files**: `skills/exp-init/SKILL.md`, `skills/exp-analyze/SKILL.md`, `skills/exp-loop/SKILL.md`, `README.md`

- `exp-init`: the interview asks for the completion contract and writes the
  `run_completion` block; the four keys and what each means.
- `exp-analyze`: producing the required artifacts is what clears the gate; name
  `omx close-check`.
- `exp-loop`: close-out runs `close-check`; the remote receipt path (§5) for a tree
  behind ssh.
- Check `test_skills_reference_real_verbs.py` still passes — it pins skill prose to
  real CLI verbs, so the new verbs must be spelled exactly.

---

## Task 11 — cross-model attack on the hook

Hand `hooks/handlers.py` (the new handlers only) and their tests to a **different
model family** — `codeagent-wrapper --agent oracle --backend agy` — with the brief:
break these handlers, especially the fail-open paths and the token parser; a hook that
fails silently is the failure mode of this repository. Every claim it returns is
checked against the code before it is acted on; a claim that does not reproduce is
recorded as not reproduced, not fixed.

---

## Task 12 — version bump, CHANGELOG, PR

- `.claude-plugin/plugin.json` → `0.17.0`; `scripts/sync_version.py` / `test_version_sync.py`
  decide whether anything else moves.
- `CHANGELOG.md` `## [0.17.0] - 2026-09-19 — <one line>` in the house narrative style:
  what happened, what the defect was *not*, what is now enforced, what is out of scope.
- Full suite green with **no fewer tests than the baseline**.
- Branch, commit, PR with a Summary and a Test-plan checklist.

---

## Task 13 — real-session firing check

A string test is not the consumer. In an actual Claude Code session with the plugin
installed from this working copy, on a fixture project with an `incomplete` contract,
run one of the three closure commands and confirm the deny reaches the session. Then
`omx close-defer` and confirm it passes. Record the transcript evidence.

---

## Out-of-repo follow-ups (separate commits, separate repositories)

- **F1** — albc profile gains a `run_completion` block (in the container, that
  repository's own commit). Nothing about it comes back into omx.
- **F2** — `agentic-cockpit`: ADR proposing the cross-harness shape (§9). Design only.
  Bound by cockpit M4 (ask, do not choose), M6 (no vendor calls unless opened), M9
  (ADR), M10 (verbatim §0 record), M7 (no `om*` names), S10 (docs on `main`).
- **F3** — auto-memory `feedback_sleep_means_launch_first` claims enforcement by
  `~/claudebase/runtime/hooks/sleep-launch-guard.py`. **Verified absent 2026-09-19**
  (not in that directory, not in any settings file; the only string match in the whole
  tree is the memory file itself). Correct the body *and* its `MEMORY.md` index line in
  the same edit.
- **F4** — move the source prompt out of `91_Inbox`.
