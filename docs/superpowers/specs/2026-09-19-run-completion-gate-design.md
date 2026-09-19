# run-completion gate — design

- **Status**: draft (D1–D5 settled by the user 2026-09-19; the rest is this document's to settle)
- **Round**: omx 0.17.0
- **Source prompt**: `2026-09-19-omx-finished-run-eval-guard-session-prompt.md`

## 0. The requester's objective, verbatim

Quoted without summary, because every decision below argues against *these* lines
and a substituted objective makes every downstream trade look correct.

> - "원래 학습런 돌리고 나서 평가 검증, 보고서 쓰는거 하나도 진행안한거가?"
> - "이 절차가 어디 기록되어있지도 않나?" · "도구가 없나?" · "이미 다 있는데 왜 안읽었는데?"
> - "대체 내가 뭘 더 해야하는데? 규칙을 얼마나 더 상세하게 작성해야하는데?" · "얼마나 더 도구를 만들어야하는데?"
> - "메모리에 남겨서 뭐하게? 어차피 니 보지도 않잖아"
> - (p6 파이프라인 스크립트에 채점 단계를 박았다고 하자) "p6 학습 할때만 동작하겠네. 다른 실험, 다른 환경, 다른 프로젝트에서는 똑같넸네"
> - "다른 세션에서 하네스 고치게 prompt 작성해"

And the goal line, also verbatim:

> **끝난 학습 런에 그 프로젝트가 정의한 평가 산출물이 없으면, 세션이 "마감·인계·완료" 를
> 선언하는 도구 호출이 막힌다.** 프로젝트·실험·머신이 바뀌어도 같은 방식으로 작동한다.

Two constraints follow from the objective and bind every section: **읽지 않아도
작동해야 한다** (so the mechanism is a tool-call boundary, never a document), and
**p6 밖에서도 작동해야 한다** (so nothing project-specific enters this repository).

## 1. Settled by the user (2026-09-19)

| # | Decision | Chosen |
|:--|:--|:--|
| D1 | Enforcement strength | **Deny + one explicit, recorded defer.** Not warn-only, not a staged observe round. |
| D2 | Where the completion contract is declared | **`run_completion` block in the omx profile (`profile/metrics.yaml`).** No new file. |
| D3 | What counts as a closure declaration | **A fixed list the harness owns.** No per-project declaration of closure verbs. |
| D4·D5 | Round scope | **Gate + STAGE-line validation + cross-harness extension design.** |

## 2. What the harness knows and what it does not

The single structural idea: **the project declares what an evaluation artifact is;
the harness only asks whether a finished run has one.** omx never learns what
`eval.py static` is, what a plant is, or what a good score looks like.

Verified against the tree this repository already has (`omx-core/omx_core/omx_paths.py`,
HEAD 71e4289):

- `paths.profile_file("metrics.yaml")` — the profile, at the omx root (`omx_paths.py:353`).
- `output_root` — read from that same file, and deliberately **outside** `.omx/`
  (`omx_paths.py:601-607`: "These live OUTSIDE .omx/. output_root originates from
  metrics.yaml and is supplied by the caller every call"). This is where checkpoints
  and evaluation artifacts actually land.
- `paths.runs_root()` — omx's *own* per-run state (`results.tsv`, `ledger.json`,
  `pending-launch.json`), not the training output tree (`omx_paths.py:595`).

The gate reads the **output tree**, not omx's run state. A run recorded in omx's
ledger is not the subject; a run whose checkpoints exist on disk is.

## 3. The contract (D2)

A new optional top-level block in `profile/metrics.yaml`:

```yaml
run_completion:
  runs:     "runs/*"                  # glob, relative to output_root -> one run directory per match
  finished: "checkpoints/*.pt"        # glob, relative to a run directory -> a match means this run FINISHED
  exclude:  ["runs/smoke-*"]          # optional; globs relative to output_root, matched against run dirs
  required:                           # globs relative to a run directory; each must match at least once
    - "eval/*.json"
    - "plots/*.png"
  how: "python analysis/eval.py static --run {run}"   # the command that produces `required`
```

Rules:

- Absent `run_completion` = **no contract**. That is a legitimate state, not an error
  (success criterion 3).
- `{run}` in `how` is substituted with the run directory path. It is the only
  substitution, and `how` is otherwise opaque — it may be a local command or an
  `ssh host '...'` line; the harness never runs it, it only prints it.
- **`rc` is never consulted anywhere.** A finished run is one whose `finished` glob
  matches, full stop. Two measured reasons: an Isaac teardown segfault turns a
  completed run into `rc=1`, and a `SystemExit` inside an Isaac kit script exits `0`.
  Neither says anything about whether the run finished.
- `exclude` is how a project keeps smoke and probe runs out of the subject set.
  Without it a five-second smoke run would demand a full evaluation.

Validation lives in `omx_core.profile` beside `validate_metrics_schema`, as a
separate `validate_run_completion` so that the bootstrap validator — which runs only
on a freshly bootstrapped profile and requires `pending_approval: true` — is untouched.

## 4. The verdict, and the three states it distinguishes

`omx close-check` is the one place the verdict is computed. The hook never
re-implements it.

| State | Condition | Verdict | Exit |
|:--|:--|:--|:--|
| `no-contract` | the profile has no `run_completion` | pass, silently | 0 |
| `checked` | contract present, `output_root` readable, every finished non-excluded run has every `required` glob | pass | 0 |
| `incomplete` | same, but at least one finished run is missing a `required` glob | **fail**, listing run → missing globs → `how` | 1 |
| `unreadable` | contract present, `output_root` absent or unreadable | **fail**, naming the root it could not read | 2 |

`unreadable` is the state this design exists to keep separate from `checked`-with-zero-runs.
A tree that could not be read returns no finished runs, and a naive check would
report that as "nothing to grade, pass". It is the same defect class 0.16.1 fixed in
`omx wiki list` — an unreadable store exiting 0 with `pages: []` — and it is the one
that would silently disarm this gate on the machine it matters on.

A readable `output_root` with genuinely zero finished runs **does** pass, and says so.

## 5. Crossing the ssh boundary

The hard problem stated in the prompt: albc's omx root and output tree are inside a
container across ssh, and hooks run on the Mac. Measured on this machine 2026-09-19:
`/Users/kimseungmin/workspace/.hq/config/experiments` exists (so `_has_omx_marker`
fires and `route_emit` injects every turn) but holds only `programs/` — **there is no
profile at the Mac root**, and no run tree.

The answer is not to teach the hook to ssh. It is to put the check where the tree is
and make the hook demand its receipt:

1. The session runs the check **where the tree lives** — locally, or
   `ssh <host> 'omx close-check --root <R> --json'`.
2. `omx close-ack --from -` ingests that JSON on the machine the hook runs on and
   stores it as a receipt under the runtime layer.
3. The gate passes on a **fresh** receipt whose verdict is `checked`.

Receipt contents: `{checked_at, root, state, runs_checked, omx_version, source}`.
Two rules keep it from becoming a bypass: `close-ack` **refuses** a receipt whose
state is not `checked` (acking a failure is the silent wave-through this gate exists
to prevent), and a receipt older than `--max-age` (default 12 h) is stale and does not
satisfy the gate.

For a local tree, `omx close-check --record` writes the same receipt directly and
step 2 is unnecessary.

## 6. The gate (D1, D3)

A `PreToolUse` handler `closure_guard`, matcher `Bash`, in the existing
`hooks/handlers.py` / `run_hook.py` fail-open dispatcher.

**Closure-declaration list — fixed, owned by the harness** (D3). Verified against the
installed CLIs 2026-09-19:

| Command | Verified |
|:--|:--|
| `hq post --category handoff` | `hq post --help` — `--category` exists |
| `omx loop-disarm --reason done` | `cli.py:2206-2212` |
| `omx loop-mark-done --reason done` | `cli.py:2214-2225` |

Parsing is **token-based** (`shlex.split`), never a regex over the raw string: a raw
regex cannot see quoting and breaks in at least six ways on real command lines. A
command that does not `shlex`-parse is not a closure declaration and passes.

Decision order, first hit wins:

1. not one of the three commands → allow
2. an active defer → allow
3. a fresh `checked` receipt → allow
4. otherwise compute the verdict in-process (same code path as `close-check`):
   - `no-contract` → **allow**, and this is the only silent pass (success criterion 3;
     the SessionStart notice in §7 is what keeps it from being invisible)
   - `checked` → allow
   - `incomplete` → **deny**, message names every missing artifact and `how`
   - `unreadable` → **deny**, message names the unreadable root, `omx close-check
     --root <R> --json` and `omx close-ack --from -`
5. any internal error → allow (the repository's standing fail-open contract, D9)

**The escape is `omx close-defer --reason "<text>"`** — it writes a dated, reasoned
entry that an audit can read, and it is what the deny message names. `OMX_SKIP_HOOKS=closure_guard`
still works, because every hook in this repository honours it, but the message does
not advertise it: a silent bypass and a recorded one are not the same act.

The deny reason is held under 1 200 characters. Hook context is capped in
**characters**, and an over-long message is truncated to a preview with no error.

## 7. The SessionStart notice

`completion_notice`, matcher `startup|resume`: when an omx layer is present and the
profile carries no `run_completion`, inject one line naming the block and where it
goes. When a contract exists it injects nothing — zero tax when healthy, the pattern
`_fetch_campaign_drift` already uses.

This is the half of success criterion 3 that carries the weight. A project with no
contract is never blocked, so the notice is the only thing standing between "this
project opted out" and "nobody ever declared one".

## 8. STAGE-line validation (D4)

Two defects were observed, and only the second one is the incident:

1. `STAGE(exp) → analyze` — a stage name outside the allowed vocabulary — passed
   unchallenged.
2. The session printed the STAGE line **as a label** and never opened that stage's
   skill. This is what actually happened for the whole p6 night.

`stage_check`, a `Stop` handler, reads the session transcript and checks both,
**session-scoped rather than turn-scoped**: a stage legitimately spans several turns
and the skill is opened once, so the question is whether the declared skill was opened
*anywhere in the session*, not in the same turn.

Transcript parsing carries two measured traps: a fixed tail window misses the turn
start, because the declaration is at the beginning of a turn and tool output after it
runs to megabytes — so the parse walks turn boundaries rather than bytes; and a user
message's `content` is sometimes a bare string rather than a list, so a parser that
assumes a list loses every turn boundary and fails open on both sides.

Blocks on: an out-of-vocabulary stage token, or a declared stage whose skill was never
opened. Allows: no STAGE line at all (`route_emit` explicitly instructs a non-experiment
turn to print none).

## 9. Cross-harness extension (D5) — design only

Design only, in `agentic-cockpit`, no code in omd/oms/omp this round. That repository's
own rules bind this part and are not optional:

- **M6** — no vendor is called for the cockpit portion unless the user opens it in that
  round. The prompt opens vendor use for the omx hook, not for this.
- **M4** — where a judgment could go either way, offer options and ask.
- **M9** — the decision lands as an ADR; an accepted ADR is never edited.
- **M10** — the user's words go into RESEARCH §0 verbatim.
- **M7** — no `om*` names survive into the new system's names.
- **S10** — documents commit on `main`.

The generalisable claim, stated so cockpit can argue with it: *every harness has a
"finished subject" and a "required artifact per subject", and each one currently
enforces neither at the tool-call boundary.* omd: a built deck with no `docs-verify`
pass. oms: a draft with no `scholar-verify` PASS. omp: a moved tree with no `omp-audit`.
Whether that shape is one mechanism or four is the ADR's question, not this document's.

## 10. Non-goals

- Nothing detects a run *finishing*; the gate fires at declaration time.
- No project content — no evaluation command, path, threshold, or plant name — enters
  this repository. The words p6, albc and IsaacLab appear nowhere in it, and a test
  enforces that.
- `closure_guard` does not look inside `ssh <host> '<cmd>'`. A closure declared only
  on the far side of an ssh is out of scope for this round and is recorded here so the
  omission is a decision rather than a blank.
- The gate never runs `how`. It prints it.

## 11. Success criteria (from the prompt, unchanged)

1. Fixture tree, finished run + no artifacts → the closure call is denied, and the
   message names the missing artifacts and the command that makes them.
2. Put the artifacts in the same tree → it passes.
3. A project with no completion contract is never blocked — and SessionStart says so once.
4. No `p6` / `albc` / `IsaacLab` anywhere in the omx repository.
5. Every existing omx test passes, plus the new ones.
