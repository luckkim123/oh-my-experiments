# OMX 다음 세션 시작 prompt — build #7 finalize/deploy + 배포 검증 (v0.1 마지막)

> 이 파일을 다음 세션에 "이 파일 읽고 시작해" 또는 "다음 작업 진행해"로 지시하면 됨.
> 작성: 2026-05-31 (build #8 구현 완료 + FINAL MERGE_READY 직후, #7 직전 compact 전).
> HEAD = main `9129173`. origin/main 대비 **38 commits ahead, NOT pushed** (#5+#6+#8 — push 미승인).

---

## 지금 어디까지 왔나 (한눈에)

OMX v0.1 = 4-skill 셋(exp-init/analyze/design/loop) + Claude-free core + **build #8 workspace-wiki 완료**.
- build #8 (workspace-wiki) **DONE + FINAL opus 7-렌즈 = MERGE_READY**. 12 commits `c6183cf`..`9129173`.
- 코어 테스트 **366 passed / 1 skipped**, working tree clean.
- **남은 건 #7 finalize/deploy 하나 — 이게 v0.1 마지막 작업.** 그 다음 배포 검증까지 한 흐름으로.

---

## 이번 세션 = #7 finalize/deploy → 배포 검증 (이어서)

**brainstorm/plan 불필요** — #7은 배포 작업이지 새 기능 설계가 아님. design §8 #7 + §6 카드 draft를 따름.

### A. #7 finalize/deploy (design §8 #7)
1. `cards/omx.json` — omha lane 카드 작성 (draft = design §6).
2. omha 등록.
3. **claudebase 등록** (settings.json + install.sh 편집) — ⚠️ **편집 직전 반드시 `git pull` claudebase 먼저**
   (메모리 [[claudebase-pull-before-register]]: claudebase에 최근 변경 많음, 로컬 clone 뒤처져 있을 것. stale base 편집 = conflict/clobber 위험). claudebase는 marketplace를 버전 핀 없이 추적 → 새 skill 자동 배포(#4와 동일)지만 등록 편집은 fresh base 필요.
4. OMC 버전 핀.
5. omx repo **public-flip + 3 repo push** — **outward-facing/비가역 → 실행 직전 1줄 confirm** (push도 유저 명시 승인 게이트).

### B. 배포 검증 (A 직후 이어서) — "deploy가 실제로 동작하는가" end-to-end
유닛테스트 366개는 이미 green — 검증 단계는 그게 아니라 **배포된 플러그인이 실제로 설치·로드·실행되는지** 확인:
- 플러그인이 claudebase/omha 경유로 **실제 설치·로드**되는가.
- fresh install 환경에서 `omx` CLI core verbs (ingest/reduce/eval/plot/init/report-parse/queue-launch/loop-status) + **wiki 4 verb (add/query/lint/list)** 가 실제로 실행되는가 (smoke-test: 임시 root에 wiki add→query→list→lint).
- 4개 skill 이 discover/invoke 되는가 (plugin.json 4 skill 인식).
- public-flip 후 repo 가 의도대로 접근 가능한가.
- 검증에서 문제 발견 시 → 그 자리에서 fix (test-first가 맞으면 superpowers 레인 재판정).

---

## 제약 (반드시 지킴)
- **claudebase 편집 직전 `git pull` claudebase 먼저** ([[claudebase-pull-before-register]]).
- **비가역/outward 단계(push, public-flip, claudebase 등록)는 실행 직전 1줄 confirm.** push는 현재 38 미승인 — 명시 승인받고 실행.
- 응답 한국어, 코드/마크다운 영어, 이모지 금지, AI-attribution 금지(git 트레일러 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`만 예외·필수).
- stage는 명시 경로만(`git add <paths>`), `git add -A` 금지(동시세션).
- `python3`(NOT `python`=Isaac). dist `omx-core/`(하이픈) vs pkg `omx_core/`(언더스코어). `pip install -e .`→`--break-system-packages`.
- 코어 테스트: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/ -q` (baseline 366 passed/1 skipped).

## 먼저 읽어라
1. `docs/design/2026-05-30-omx-experiment-harness-design.md` §8 #7 + §6 (카드 draft) — 배포 범위.
2. `docs/HANDOFF.md` — 현재 상태 (#8 DONE 기록됨).
3. 메모리 `omx-build8-workspace-wiki-2026-05-31` (#8 완료 + NEXT #7), `omx-build6-exp-loop-2026-05-30` (#7 범위), `claudebase-pull-before-register` (pull-first 가드).

## stale-wakeup / 옛 prompt 주의
- 이 파일이나 옛 ScheduleWakeup이 옛 단계(예: "T8 구현", "build #8 구현")를 가리키면 **글자대로 실행 금지** — `git log` + HANDOFF로 실제 완료 상태 먼저 확인 후 진짜 미완만 진행. build #8은 `9129173`에서 이미 완료됨.
