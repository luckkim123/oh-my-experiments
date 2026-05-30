# OMX 작업 핸드오프 (2026-05-30)

> 다음 세션/compact 이후: 이 파일 + `docs/design/2026-05-30-omx-experiment-harness-design.md`(진실원)만
> 읽으면 이어서 작업 가능. build-order별 실행 계획은 `docs/superpowers/plans/`.

## 현재 상태 (요약)

레포 `/workspace/oh-my-experiments`, 작업 브랜치 **main** (검증된 원본). **push 안 함** (유저 명시 요청 시에만). working tree clean.

### 완료된 build-order
- **#0 `omx_paths.py`** — path single-source-of-truth. 6 TDD task, merge됨 (`65fe813`).
- **#1 omx-core skeleton** — ingest + reduce + CLI + state.json. 11 TDD task + 2단 리뷰 + opus 최종 리뷰 ✅ MERGE-READY. merge됨 (`merge: omx-core skeleton`). **160 tests pass.**

### #1이 만든 것 (omx-core/omx_core/)
- `omx_paths.py` (#0) — cache 확장자만 `.parquet`→`.npz`로 수정 (pyarrow 부재).
- `state.py` — `.omx/state.json` 스키마 + atomic load/save (loop #6이 필드 채움).
- `ingest/` — `IngestResult`/`SummaryRecord`(long-form) + `IngestAdapter` ABC; `EvalSummaryAdapter`(eval_dr summary.json), `LongFormCsvAdapter`(flat CSV), `WandbAdapter`/`TensorboardAdapter` stubs(→ #4 deferred, NotImplementedError).
- `reduce/` — `summarize`(to_dataframe + add_cv=std/mean, 03-analysis-quality 룰), `series`(load_npz + downsample axis-0 stride), `plot`(headless Agg PNG, width cap), `cache`(atomic npz, np.savez file-object form).
- `cli.py` — `omx` CLI: `ingest` / `reduce summarize` / `session-id`(flag>env>autogen B2). console script 등록됨.

**검증:** `cd omx-core && python3 -m pytest tests/ -q` → **160 passed**. 순수 stdlib + numpy/pandas/matplotlib/pyyaml. Claude/Isaac/network 0 의존. opus 최종: 0 Critical/Important, coherence/path-SSOT/loud-fail 감사 전부 PASS.

### 실제 데이터 ground-truth (검증됨 — #4에서 재사용)
- eval_dr `summary.json` = `{dr_level: {axis: {field: float}}}`. dr_level∈{none,soft,medium,hard}, axis∈{roll,pitch,vx,vy,vz,yaw,att_norm(4필드만), survival_pct(스칼라)}, full axis=15필드.
- `data_*.npz` = trajectory (7750,4)=(timesteps,n_envs) + target (7750,) + time_to_failure (4,).
- pyarrow 미설치 → cache는 `.npz`.

### 다음에 할 일 (design §8 수정 DAG)
**build-order #2 — Evaluator-contract runner + Isaac Lab reference profile:**
- 커밋된 reference `evaluator.sh` 소비, `{pass, score?}` 파싱(contracts.ts:178-201), keep-policy 배선.
- score는 `score_improvement`에서만 필수, reference는 `pass_only` 배포 (B5).
- **코딩 전 결정 (B6)**: keep/discard 대상 = config-git-revert + checkpoint-pointer(ledger.json `last_kept_checkpoint`). RL weight는 git에 없음.
- 별도 writing-plans → subagent-driven-development (이번 #1과 동일 패턴).

**이후:** #3 exp-init(토폴로지 §4.1, H4 root-discovery 소유) → #4 exp-analyze(PNG-vision, WandB/TB 어댑터 실구현) → #5 exp-design → #6 exp-loop → #7 cards/omx.json + omha + installer.

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
