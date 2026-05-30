# OMX 다음 세션 시작 prompt — build-order #5 `exp-design` skill

> 이 파일을 다음 세션에 그대로 붙여넣거나, "이 파일 읽고 시작해" 라고 지시하면 됨.
> 작성: 2026-05-30 (build #4 exp-analyze merge + push 직후). HEAD = main `642140a`, origin/main과 동기화됨 (build #0-4 전부 push 완료).

---

## 붙여넣을 prompt (이 블록만 복사해도 됨)

```
OMX build-order #5 (exp-design skill) 진행. ew opus.

먼저 읽어라 (순서대로):
1. docs/HANDOFF.md — 현재 상태 + 환경 함정
2. docs/design/2026-05-30-omx-experiment-harness-design.md
   §4 (skills 표, exp-design 행) + §5/§6 (trace 3-lane diagnosis →
   discriminating-probe = 이게 #5의 핵심 IP) + §8 #5 + §10 (proposals 트리)
3. skills/exp-analyze/SKILL.md — #4가 만든 분석 스킬. #5는 그 report.md를 입력으로 받음.
4. 메모리 omx-build4-exp-analyze-2026-05-30 (이미 컨텍스트에 로드됨)

작업: design §4 + trace 3-lane + §10 그대로 exp-design 스킬 + 받쳐주는 코어를 구현.
- exp-design = exp-analyze의 evidence-tagged report를 입력으로, 3-lane 차별 진단
  (code-path / config-DR-hyperparam / measurement-artifact)을 수행 → 가설을 가르는
  discriminating probe를 산출. 그 probe가 곧 "다음 실험 config 제안"임.
- 산출물: `<output_root>/<run_id>/proposals/<proposal_id>.md` (pending approval).
  exp-init의 hard gate와 동일하게, 제안은 절대 자동 실행 안 됨 (훈련 launch 금지).
- Claude-required 스킬 (진단 판단). 코어(Claude-free)는 proposal 트리 경로 getter +
  atomic write IO만 담당 (omx_paths에 proposal_md/proposals_dir getter가 이미 있는지
  먼저 확인 — 없으면 #5에서 추가, 있으면 재사용).

워크플로우: superpowers writing-plans → subagent-driven-development.
- #3/#4에서 검증된 패턴 그대로: task별 fresh implementer(sonnet) → spec 리뷰(haiku)
  → quality 리뷰(sonnet) → 통과 시 다음 → 전체 끝나면 opus 최종 리뷰 →
  finishing-a-development-branch(merge-local → push는 유저 명시 승인 시).
- plan 쓰기 전 ground-truth recon 필수:
  (a) design의 trace 3-lane 정의 + discriminating-probe 산출 규칙,
  (b) omx_paths에 proposal_* getter 존재 여부 (있으면 시그니처, 없으면 추가 설계),
  (c) exp-analyze report.md/manifest.json 포맷 (exp-design의 입력 계약),
  (d) skills/exp-analyze/SKILL.md의 evidence-tag 포맷 ([FINDING]/[EVIDENCE]/[CONFIDENCE]) —
      exp-design은 이 태그를 읽어 lane을 가름.

제약 (반드시 지킴):
- 훈련/eval 자동발사 금지 — exp-design은 proposal md만 씀 (pending approval). 새 훈련 launch 절대 없음.
- omx-core의 Claude-free 부분(paths/ingest/reduce/eval)은 Claude-free 유지. 스킬(Claude)과 경계 안 흐림.
  3-lane 진단 판단은 스킬(Claude) 몫, proposal 트리 파일생성/검증은 코어(파이썬) 몫.
- 절대경로/private repo명 박지 말 것 (public repo). placeholder.
- 커밋은 중요 변화마다 자동, 메시지 끝 Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>.
- push는 유저 명시 요청 시만. 작업 끝나면 plugin.json skills:[]에 exp-design 등록.
- 응답은 한국어. 코드/주석/마크다운은 영어. 이모지 금지. AI-attribution 텍스트 금지(git 트레일러는 예외).
```

---

## 다음 세션이 알아야 할 현재 상태 (요약)

### 완료 (엔진 + 배포 + 스킬 2개)
- **#0/#1/#2** = 엔진 (paths/ingest/reduce/cli/evaluator-runner). main 병합.
- **#3 exp-init** = 첫 스킬 (인터뷰 → profile bootstrap). main 병합.
- **#4 exp-analyze** = 둘째 스킬 (hybrid PNG-vision 분석 + WandB/TB 어댑터 실구현). **main 병합 + push 완료** (merge `43963f9`). **278 passed / 1 skipped.**
  - 실 ingest 어댑터: `ingest/tensorboard.py`(EventAccumulator) + `ingest/wandb_offline.py`(offline `.wandb` datastore parse). 둘 다 `_step/<key>` x-axis companion emit (한 계약). stub 은퇴.
  - `profile.load_profile`(B1 vocabulary tier), `reduce/promote.py`(B3 plot promotion), `omx plot`/`omx promote-plots` verbs, `analyze` optional-deps extra + import guard, `skills/exp-analyze/SKILL.md`(§5 hybrid router).
- **배포**: omx repo PUBLIC, self-hosted marketplace(`.claude-plugin/marketplace.json`), claudebase 등록(`settings.json` enabledPlugins + extraKnownMarketplaces, 버전 핀 없음 = 최신 추적). plugin.json = exp-init + exp-analyze 2개 skill.

### 미완 (= 다음 세션들)
- **스킬 2개 미구현**: exp-design(#5, 다음) → exp-loop(#6).
- **plugin.json skills**: 현재 2개. #5 끝나면 exp-design 추가.
- **legitimate deferral** (갭 아님): `tables/` 출력 트리(`analysis_table` getter는 있으나 미사용, future hook), NaN 가드(#2 Minor → #6에서 처리).

### 남은 build 순서 (design §8 DAG)
```
#5 exp-design   ← 다음 (trace 3-lane 진단 → discriminating probe = 다음 실험 제안)  [이 세션]
#6 exp-loop     (자율 루프 + 퇴근토글, 훈련 자동발사 금지 = 큐잉; #2 Minor NaN 가드도 여기)
#7 plugin.json skills 채우기 + 완성
```

### 환경 함정 (HANDOFF.md 상세, 핵심만)
- `python` = Isaac 래퍼 → 반드시 `python3` (3.12.3, pytest 9.x).
- `pip install -e .` → `--break-system-packages` 필요.
- dist dir = `omx-core/`(하이픈), import pkg = `omx_core/`(언더스코어). cache = `.npz`.
- Pyright `reportMissingImports`(omx_core.*) + protobuf dynamic-attr = 전부 editable/false positive, 무시.
- 백그라운드 subagent에 SendMessage로 review-fix 시 완료 알림이 1턴 늦을 수 있음 → 깨어나면 git log로 실제 상태 먼저 확인.
- 리뷰어 프롬프트엔 추측 SHA 금지, implementer 완료 후 git log로 실제 SHA 확인해 전달.
