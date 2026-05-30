# OMX 작업 핸드오프 (2026-05-30)

> 다음 세션/compact 이후: 이 파일 + `docs/design/2026-05-30-omx-experiment-harness-design.md`(진실원)만
> 읽으면 이어서 작업 가능. build-order별 실행 계획은 `docs/superpowers/plans/`.

## 현재 상태 (요약)

레포 `<repo>`. **#2 작업 브랜치 `feat/omx-evaluator`** (main 미병합, 8 commit `bc07337..c681b52`). working tree clean.
**이번 세션 범위 = #2 구현 + (이후) public 전환 + claudebase/marketplace 등록 + push.** push는 유저가 이번 세션에 명시 요청함(원래 "push 안 함" 철회됨) — 단 #2 검토 완료 후 배포 단계에서 묶어서.

### 완료된 build-order
- **#0 `omx_paths.py`** — path single-source-of-truth. 6 TDD task, merge됨 (`65fe813`).
- **#1 omx-core skeleton** — ingest + reduce + CLI + state.json. 11 TDD task + 2단 리뷰 + opus 최종 리뷰 ✅ MERGE-READY. merge됨. **160 tests pass.**
- **#2 evaluator-contract runner + Isaac Lab reference** — ✅ **MERGE-READY** (브랜치 `feat/omx-evaluator`, 미병합·미push). 7 TDD task, 각 spec+quality 2단 리뷰 통과(fix 0라운드) + opus 최종 cross-cutting 리뷰 라이브검증 MERGE-READY. **221 passed / 1 skipped.** 계획=`docs/superpowers/plans/2026-05-30-omx-evaluator-runner.md`(4-렌즈 적대리뷰 SOUND, 커밋 `c681b52`).
  - 만든 것: `evaluator.py`(parse_evaluator_result loud-fail + run_evaluator subprocess LAST-line fault-recorded) / `decision.py`(parse_keep_policy + decide_outcome keep/discard/ambiguous/bootstrap, B5) / `ledger.py`(trio writers + seed_ledger 불변 baseline + record_iteration B6 pointer) / `reference/isaaclab/evaluator.sh`(pass_only stub) / `omx_paths.py`(+OmxError base, +reference_dir/reference_evaluator/checkpoint_pointer_json) / `cli.py`(+`omx eval`).
  - **B6 LOCKED**: config→git SHA(baseline_commit 불변 anchor + last_kept_commit) / weights→last_kept_checkpoint 포인터(keep advance, 非keep leave, weight 파일에 git/rm 절대 없음). checkpoint-pointer.json mirror(ledger authoritative).
  - opus가 남긴 **Minor 1건(미적용, defer 가능)**: `omx eval`이 non-finite score를 strict-JSON 위반 `NaN`으로 출력(형제 `_cmd_reduce_summarize`엔 `allow_nan=False` 가드 있음). pass_only 경로 안 닿고 크래시 없음 → #3(score formula)에서 `_is_number`에 `math.isfinite` + `_cmd_eval`에 allow_nan=False.

### #1이 만든 것 (omx-core/omx_core/)
- `omx_paths.py` (#0) — cache 확장자만 `.parquet`→`.npz`로 수정 (pyarrow 부재).
- `state.py` — `.omx/state.json` 스키마 + atomic load/save (loop #6이 필드 채움).
- `ingest/` — `IngestResult`/`SummaryRecord`(long-form) + `IngestAdapter` ABC; `EvalSummaryAdapter`(eval_dr summary.json), `LongFormCsvAdapter`(flat CSV), `WandbAdapter`(offline `.wandb` datastore parse) / `TensorboardAdapter`(EventAccumulator) — real adapters as of build #4, heavy imports deferred.
- `reduce/` — `summarize`(to_dataframe + add_cv=std/mean, 03-analysis-quality 룰), `series`(load_npz + downsample axis-0 stride), `plot`(headless Agg PNG, width cap), `cache`(atomic npz, np.savez file-object form).
- `cli.py` — `omx` CLI: `ingest` / `reduce summarize` / `session-id`(flag>env>autogen B2). console script 등록됨.

**검증:** `cd omx-core && python3 -m pytest tests/ -q` → **160 passed**. 순수 stdlib + numpy/pandas/matplotlib/pyyaml. Claude/Isaac/network 0 의존. opus 최종: 0 Critical/Important, coherence/path-SSOT/loud-fail 감사 전부 PASS.

### 실제 데이터 ground-truth (검증됨 — #4에서 재사용)
- eval_dr `summary.json` = `{dr_level: {axis: {field: float}}}`. dr_level∈{none,soft,medium,hard}, axis∈{roll,pitch,vx,vy,vz,yaw,att_norm(4필드만), survival_pct(스칼라)}, full axis=15필드.
- `data_*.npz` = trajectory (7750,4)=(timesteps,n_envs) + target (7750,) + time_to_failure (4,).
- pyarrow 미설치 → cache는 `.npz`.

### 다음에 할 일 (이번 세션 — compact 후 즉시 재개)
**배포 단계 (유저 요청, #2 검토 완료 후 묶어서):** 순서 = (a) `feat/omx-evaluator` → main 병합(finishing-a-development-branch, merge-local) → (b) omx repo public 전환 → (c) claudebase + marketplace 등록 → (d) push 3곳. **전부 outward-facing/비가역이라 실행 직전 1줄 confirm.**

**등록 메커니즘 (recon 완료 — 정확한 파일·명령):**
- omx repo: `github.com/luckkim123/oh-my-experiments` 현재 **PRIVATE** → `gh repo edit luckkim123/oh-my-experiments --visibility public`.
- omha 카드: `<plugins>/marketplaces/heroacademia/cards/omx.json` 신규작성(design §6 내용 그대로) — glob 발견이라 index 편집 불필요. heroacademia는 **shallow clone**(push는 됨), remote=`luckkim123/oh-my-heroacademia`. 추가로 그 repo `.claude-plugin/marketplace.json`에 oh-my-experiments entry.
- OMX manifest: `<repo>/.claude-plugin/{plugin.json,marketplace.json}` 신규(skills 배열 `[]` — #3~#6 전). plugin.json: name=oh-my-experiments, version 0.1.0.
- claudebase(`<claudebase>`, remote=`luckkim123/claudebase`): `config/settings.json`(enabledPlugins `"oh-my-experiments@omx": true` + extraKnownMarketplaces `omx`) + `installer/install.sh`(OMX marketplace block + OMC 버전핀 `pin_omc_version()`; 현재 OMC 4.14.1 설치/4.14.4 캐시 — **핀 버전 유저확인 필요**, sync_plugins는 version 미추적이라 installed_plugins.json 직접 읽는 별도 함수).
- push 3곳: oh-my-experiments(full clone) + oh-my-heroacademia(shallow) + claudebase.

**이후 (다음 세션 — design §8 DAG):** #3~#6 전부 DONE → **#7 마무리**(cards/omx.json + omha 등록 + claudebase installer + OMC 버전핀; design §8 #7). 그 후 (post-v0.1) #8 workspace-specialization wiki(§9, registry/findings를 OMC-wiki식 키워드 인덱스 레이어로 승격 — 별도 brainstorm+plan 필요).

- **#4 exp-analyze — DONE + MERGED + PUSHED** (merged to `main` via no-ff `43963f9`, pushed to origin/main; branch `feat/omx-exp-analyze` deleted). 만든 것: `TensorboardAdapter`(EventAccumulator 실구현) + `WandbAdapter`(offline `.wandb` datastore parse) — stub→real, heavy imports deferred, both emit a `_step/<key>` x-axis companion (one adapter contract; FINAL-review fix `a3020b6`); `load_profile`(metrics.yaml→Profile, B1 vocabulary tier 활성화); B3 plot promotion 코어(`reduce/promote.py`) + `omx plot` / `omx promote-plots` CLI verbs; `analyze` optional-deps extra + import-safety guard 테스트; `skills/exp-analyze/SKILL.md`(§5 hybrid router: code-exec 정확수치/PNG-vision shape/overlay/eval JSON, evidence tags [FINDING]/[EVIDENCE]/[CONFIDENCE], atomic_path 경유 report.md/manifest.json 영구트리 기록). **278 passed / 1 skipped.** plugin.json 에 2개 skills 등록(exp-init + exp-analyze); FINAL opus review = MERGE_READY. NEXT = #5 exp-design.

- **#5 exp-design — DONE** (branch `feat/omx-exp-design`, 미병합·미push). 만든 것: 코어 `omx_core/report.py`(`Finding` 데이터클래스 + `parse_findings(text)->list[Finding]` — exp-analyze report.md의 `[FINDING]`/`[EVIDENCE]`/`[CONFIDENCE]` triplet 파서; orphan·malformed·bad-keyword 태그 런은 `ReportParseError` loud-fail, `_ANY_TAG` 가드로 silent-drop 차단) + `omx report-parse` CLI verb(Claude-free, rc 0 + `{n_findings, findings:[]}` / rc 2 loud-fail) + `Finding`/`parse_findings`/`ReportParseError` export. `skills/exp-design/SKILL.md`(3-lane 차별 진단: code-path / config-DR-hyperparam / measurement-artifact — OMC trace 패턴 재구현 → evidence FOR/AGAINST + critical unknown per lane → 가장 싼 discriminating probe = 다음 실험; report는 `omx report-parse`로만 읽고 hand-parse 금지; proposal은 기존 `proposal_md` getter + `atomic_path`로 `proposals/<TS>-next.md` 영구트리에 pending-approval로 기록; hard gate = 훈련/eval 자동발사 금지·one-variable·모든 숫자 finding 추적). **새 코어 path 코드 0**(proposal_md/atomic_path 재사용). **292 passed / 1 skipped.** 각 task spec+quality 2단 리뷰 통과(T2 orphan bad-keyword fix + T3 with-open/zero-findings polish). plugin.json skills = [exp-init, exp-analyze, exp-design] 3개. NEXT = **#6 exp-loop**(여기서 #2 Minor NaN 가드도 처리).

- **#6 exp-loop — DONE + on local main (미push)** (이 세션들은 main 직접 커밋 패턴; 별도 feature branch 없음, origin/main 대비 21 ahead). 만든 것: 코어 `omx_core/loop.py`(`compute_deadline`/`deadline_passed` — pure·time-injected deadline ceiling, caller가 ISO now 주입해 wall-clock 없이 테스트 가능; `queue_pending_launch`/`read_pending_launch` — `runs/<id>/pending-launch.json` atomic write, status='pending approval', corrupt-JSON loud-fail) + `omx_paths.pending_launch_json(run_id)` getter(유일한 새 path) + `omx queue-launch`(real-clock 주입 후 큐잉, **절대 launch 안 함**)/`omx loop-status`(`--max-runtime`로 compute_deadline 호출해 deadline_passed + pending_launch JSON 보고; explicit `--deadline` 우선) CLI verbs + `omx_core` export. `skills/exp-loop/SKILL.md`(analyze[exp-analyze]→design[exp-design]→eval[omx eval]→keep/discard[decision]→log[ledger]→queue-launch→stop/repeat 오케스트레이터; "퇴근 토글" deadline은 analyze/design/eval만 게이트; 훈련 launch는 `omx queue-launch`로 pending-approval 큐잉만, **자동발사 절대 금지** D4/B8; keep/discard target = config git-revert 명령 surface(자동실행 금지)+checkpoint 포인터 B6; no-max-runtime이면 단일패스 안전기본). **새 훈련 launch 0, NaN 가드는 #3에서 이미 처리됨(여기 작업 아님).** **314 passed / 1 skipped.** 각 task spec+quality 2단 리뷰 통과(T3 corrupt-JSON 테스트, T5 loud-fail try-block, T6 deadline-compute 갭 = 리뷰가 잡은 실결함 fix). plugin.json skills = [exp-init, exp-analyze, exp-design, exp-loop] **4개 완성**. NEXT = **#7 마무리**(omha card + claudebase 등록; **claudebase 등록 전 `git pull` 필수** — 유저 지시, memory `claudebase-pull-before-register`).

- **#3 exp-init — DONE** (branch `feat/omx-exp-init`, 미병합·미push). 만든 것: `omx_core/profile.py`(`validate_metrics_schema` loud-fail 검증 + `bootstrap_profile` atomic 4-file write + `default_metrics`) + `omx init` CLI verb(profile.bootstrap의 thin entry, rc 0/2) + `skills/exp-init/SKILL.md`(deep-interview 3-dim 게이트 재구현: Goal 0.40/Criteria 0.30/Constraints 0.30, threshold 0.2; 5 토픽→3 dim 매핑 §4.1; AskUserQuestion 대신 prose 번호옵션; `omx init` 핸드오프 + pending-approval hard gate) + plugin.json 등록. **부수 수정**: `main()`이 string-coded SystemExit 메시지를 stderr로 surface(이전엔 rc=2에 메시지 손실 — loud-fail 위반이었음, build #3 리뷰에서 발견). **252 passed / 1 skipped.** 각 task spec+quality 2단 리뷰 통과. NEXT = #4 exp-analyze(PNG-vision, WandB/TB 어댑터 실구현; profile의 vocabulary tier 활성화).
  - 참고: line 17의 "#3에서 `_cmd_eval` allow_nan=False 처리" Minor는 이미 해결됨(`2191736`에서 `_cmd_eval`에 `allow_nan=False` 들어감). 그 항목은 stale.

### opus가 남긴 #1 Minor (전부 polish, 미적용 — 의도)
M1 csv/eval float() 에러에 row/file 컨텍스트 없음(이미 loud-fail) · M2 session-id 초단위(pid로 충분) · M3 plot docstring "cap"이 tight-bbox에선 근사 · M4 dep 상한 없음(research tool엔 정상). 모두 future-hardening, 차단 아님.

## 환경 함정 (이미 데인 것들)
- `python` = Isaac Sim 래퍼. **반드시 `python3`** (3.12.3 + pytest 9.0.2).
- `pip install -e .`는 PEP 668 → `--break-system-packages` 필요 (root Docker, 안전).
- Pyright `reportMissingImports` (omx_core.*) + summarize.py `.rename` ndarray 경고 = editable/pandas-stub false positive — 무시.
- 배포 dir = `omx-core/`(하이픈), import 패키지 = `omx_core/`(언더스코어). cache = `.npz`(parquet 아님).
- tool 출력이 종종 1턴 늦게/한꺼번에 렌더됨(transport 지연, state 손상 아님). cwd가 `cd omx-core` 후 상대경로 재진입에서 오염되니 절대경로 또는 repo-root cd 사용.
- `AskUserQuestion`이 이 환경에서 guard 훅 누락으로 실패 → 결정은 prose 권장안+진행으로 대체.

## subagent-driven 실행 패턴 (검증됨, #0·#1 재사용)
task별 fresh implementer(sonnet) → spec 리뷰(haiku) → quality 리뷰(sonnet) → 통과 시 다음 → 전체 끝나면 opus 최종 리뷰 → finishing-a-development-branch (merge-local, push 안 함).
**교훈 (#1에서 데임):** implementer와 리뷰어를 동시 디스패치하며 리뷰어 프롬프트에 **추측 SHA**를 박지 말 것 — 실제 SHA는 commit 후에야 정해짐(대부분 리뷰어가 git log로 복구했지만 1건 오진). implementer 완료 후 실제 SHA 확인하고 리뷰어 디스패치. quality 리뷰엔 "테스트가 실제 코드 분기를 밟는가" 명시 지시(죽은 width-cap 테스트 거기서 잡힘).

## 잠긴 설계 결정 (재논의 금지 — design §0.1)
B1 2-tier 검증 / B2 session_id(flag→env→autogen) / B3 report.md 영구트리 단일홈+plot promotion /
B4 DAG(exp-init #3, evaluator #2=reference profile) / B5 score pass_only선택·score_improvement필수 /
B6 revert=config git+checkpoint 포인터 / B7 card url 선언적 / B8 훈련 launch 자동발사 금지(큐잉) / D3 MCP 서버 없음.
