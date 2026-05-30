# OMX 다음 세션 시작 prompt — build-order #4 `exp-analyze` skill

> 이 파일을 다음 세션에 그대로 붙여넣거나, "이 파일 읽고 시작해" 라고 지시하면 됨.
> 작성: 2026-05-30 (build #3 exp-init merge 직후). HEAD = main `786afb2` (origin보다 15 커밋 앞섬, **미push** — push는 유저 게이트).

---

## 붙여넣을 prompt (이 블록만 복사해도 됨)

```
OMX build-order #4 (exp-analyze skill) 진행. ew opus.

먼저 읽어라 (순서대로):
1. docs/HANDOFF.md — 현재 상태 + 환경 함정
2. docs/design/2026-05-30-omx-experiment-harness-design.md
   §4 (skills 표, exp-analyze 행) + §5 (analysis hybrid router — 이게 #4의 핵심 IP) +
   §8 #4 + §10.1 (B3 plot promotion 규칙 + 영구 output 트리 레이아웃)
3. skills/exp-init/SKILL.md — #3가 만든 첫 스킬. #4는 이게 만든 profile을 READS.
4. 메모리 project-omx-harness-2026-05-30 (이미 컨텍스트에 로드됨)

작업: design §4 + §5 + §10.1 그대로 exp-analyze 스킬 + 받쳐주는 코어를 구현.
- exp-analyze = N개 run의 런타임 분석. profile(metrics.yaml)을 읽어 vocabulary tier(B1)를 활성화.
  hybrid router(§5): summary-stat-first → shape 질문이면 PNG-vision → 정확수치는 code-exec.
- Claude-required 스킬 (PNG-vision, H3) — ingest/reduce는 Claude-free 코어가 이미 함.
- 산출물: report.md (영구 트리 <output_root>/<run_id>/analysis/<analysis_id>/, B3) +
  promoted PNG + evidence-tagged findings([FINDING]/[EVIDENCE]/[CONFIDENCE]).
- plot promotion(B3): 후보 PNG는 scratch/<sid>/plots/에 먼저, report.md가 참조한 것만
  영구 analysis/<aid>/plots/로 os.replace 승격. 미참조는 scratch에 남아 omx clean이 쓸어감.
- WandbAdapter / TensorboardAdapter (ingest/stubs.py, 현재 NotImplementedError) 실구현 —
  실데이터로 검증. eval_dr summary.json은 이미 EvalSummaryAdapter가 처리.

워크플로우: superpowers writing-plans → subagent-driven-development.
- #3에서 검증된 패턴 그대로: task별 fresh implementer(sonnet) → spec 리뷰(haiku) → quality 리뷰(sonnet)
  → 통과 시 다음 → 전체 끝나면 opus 최종 리뷰 → finishing-a-development-branch(merge-local, push 안 함).
- plan 쓰기 전 ground-truth recon 필수: (a) §5 hybrid router 4분기 표, (b) reduce/plot.py·series.py의
  실제 시그니처(이미 있음 — PNG 생성/downsample), (c) omx_paths의 analysis_dir/report_md/manifest_json/
  analysis_plot/analysis_table + scratch_plots getter(이미 있음), (d) Profile vocabulary tier가
  metric/view/agg를 어떻게 검증하는지(omx_paths._check_token).
- 새 CLI verb가 필요한지 plan에서 결정: `omx analyze`는 Claude-required라 순수-파이썬 verb가 아닐 수 있음.
  대신 스킬이 ingest/reduce/plot 코어를 조립 호출 + PNG를 vision으로 되읽는 구조(§4 "thin Claude wrapper").
  plot 생성/promotion 같은 파일 IO·검증은 코어(omx_paths atomic_dir/atomic_path)에 둘 것 — D8.

제약 (반드시 지킴):
- 훈련/eval 자동발사 금지 — exp-analyze는 이미 존재하는 run 결과를 분석만. 새 훈련 launch 절대 없음.
- omx-core의 Claude-free 부분(ingest/reduce/eval/paths)은 Claude-free 유지. 스킬(Claude)과 경계 안 흐림.
  PNG-vision·evidence-tag 판단은 스킬(Claude) 몫, exact arithmetic·plot 파일생성은 코어(파이썬) 몫.
- 절대경로/private repo명 박지 말 것 (public repo). placeholder.
- 커밋은 중요 변화마다 자동, 메시지 끝 Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>.
- push는 유저 명시 요청 시만. 작업 끝나면 plugin.json skills:[]에 exp-analyze 등록(#7 점진).
- AskUserQuestion이 이 환경에서 깨짐(guard 훅 stale path, claudebase-rename 메모리 참조) →
  결정은 prose 권장안+진행. fix 0eee90d 미배포 상태.
```

---

## 다음 세션이 알아야 할 현재 상태 (요약)

### 완료 (엔진 + 배포 + 첫 스킬)
- **#0/#1/#2** = 엔진 (paths/ingest/reduce/cli/evaluator-runner). main 병합.
- **#3 exp-init** = 첫 스킬. main 병합 (merge 커밋 `786afb2`). **252 passed / 1 skipped.**
  - `omx_core/profile.py`(validate_metrics_schema + bootstrap_profile + default_metrics) +
    `omx init` CLI verb + `skills/exp-init/SKILL.md`(3-dim 게이트, prose 옵션, pending-approval hard gate) +
    plugin.json 등록. 부수: `main()`이 loud-fail 메시지를 stderr로 surface(이전엔 rc=2에 손실).
- **배포** (이전 세션): omx repo PUBLIC, 자체 marketplace, heroacademia 카드(cards/omx.json, exp-analyze 이미 triggers.skills에 등록됨), claudebase 등록. 단 #3·#4 산출물은 **미push**.

### 미완 (= 다음 세션들)
- **스킬 3개 미구현**: exp-analyze(#4, 다음) → exp-design(#5) → exp-loop(#6).
- **ingest stub 2개**: WandbAdapter / TensorboardAdapter (`ingest/stubs.py`, NotImplementedError) → **#4가 실구현**.
- **plugin.json skills**: 현재 `["./skills/exp-init/"]` 1개. #4 끝나면 exp-analyze 추가.
- **미push**: main이 origin보다 15 커밋 앞섬. 유저가 push 지시하면 그때.

### 실데이터 ground-truth (#1에서 검증, #4에서 재사용)
- eval_dr `summary.json` = `{dr_level: {axis: {field: float}}}`. dr_level∈{none,soft,medium,hard},
  axis∈{roll,pitch,vx,vy,vz,yaw,att_norm(4필드),survival_pct(스칼라)}, full axis=15필드.
- `data_*.npz` = trajectory (7750,4)=(timesteps,n_envs) + target (7750,) + time_to_failure (4,).
- pyarrow 미설치 → cache는 `.npz`.

### 남은 build 순서 (design §8 DAG)
```
#4 exp-analyze  ← 다음 (PNG-vision hybrid router, WandB/TB 어댑터 실구현)   [이 세션]
#5 exp-design   (trace 3-lane 진단 → discriminating probe = 다음 실험 제안)
#6 exp-loop     (자율 루프 + 퇴근토글, 훈련 자동발사 금지 = 큐잉; #2 Minor NaN 가드도 여기)
#7 plugin.json skills 채우기 + 완성
```

### 환경 함정 (HANDOFF.md 상세, 핵심만)
- `python` = Isaac 래퍼 → 반드시 `python3` (3.12.3, pytest 9.x).
- `pip install -e .` → `--break-system-packages` 필요.
- dist dir = `omx-core/`(하이픈), import pkg = `omx_core/`(언더스코어). cache = `.npz`.
- cwd 오염: `cd omx-core` 후 상대경로 재진입하면 깨짐 → 절대경로 또는 repo-root에서.
- Pyright `reportMissingImports`(omx_core.*) + `from __future__ import annotations` unreachable +
  unused pytest/capsys = 전부 editable/fixture false positive, 무시.
- 백그라운드 subagent에 SendMessage로 review-fix 시킬 때: 완료 알림이 1턴 늦을 수 있음.
  fallback wakeup을 걸면 stale 발화로 뒤늦게 깨어날 수 있으니, 깨어나면 먼저 git log로 실제 상태 확인.
```
