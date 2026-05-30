# OMX 다음 세션 시작 prompt — build-order #6 `exp-loop` skill

> 이 파일을 다음 세션에 그대로 붙여넣거나, "이 파일 읽고 시작해" 라고 지시하면 됨.
> 작성: 2026-05-30 (build #5 exp-design merge-to-local-main 직후). HEAD = main `b39944d` (no-ff merge of #5).
> origin/main 대비 **10 commits ahead, NOT pushed** (build #5 전체 — 유저가 push는 아직 승인 안 함).

---

## 붙여넣을 prompt (이 블록만 복사해도 됨)

```
OMX build-order #6 (exp-loop skill) 진행. ew opus.

먼저 읽어라 (순서대로):
1. docs/HANDOFF.md — 현재 상태 + 환경 함정 (#5 DONE bullet 포함)
2. docs/design/2026-05-30-omx-experiment-harness-design.md
   §4 (skills 표, exp-loop 행) + §8 #6 + §10.2 (runs/<id> 트리: results.tsv/ledger.json/
   decision-log.md/checkpoint-pointer.json) + D4/B8 (훈련 launch는 큐잉, 절대 자동발사 금지)
   + B6 (revert target = config git-revert + checkpoint 포인터) + §9 (B6/B8 carry, 미해결 항목)
3. skills/{exp-analyze,exp-design}/SKILL.md — #6은 이 둘을 호출/조율함 (analyze->design->eval 루프)
4. 메모리 omx-build5-exp-design-2026-05-30 (이미 컨텍스트에 로드됨)

작업: design §4 exp-loop 행 + autoresearch 루프 모양 + §10.2 ledger 트리를 구현.
- exp-loop = 반자율 루프: analyze -> design -> eval(contract) -> keep/discard -> log -> repeat.
  "퇴근 토글"은 analyze+design+eval 단계만 자율 (max-runtime ceiling). 훈련 launch는
  **절대 자동발사 안 함** — 다음 launch를 `pending approval` 아티팩트로 큐잉만 (D4/B8,
  repo 룰 "훈련 종료/시작은 유저가 직접" override 경로 없음).
- keep/discard 게이트: config/hyperparam 수정 -> git revert; 학습 weights -> ledger.json의
  last_kept_checkpoint 포인터(keep=advance, discard=leave, weight 파일에 git/rm 절대 없음). B6.
- 산출물: `.omx/runs/<run_id>/{results.tsv, ledger.json, decision-log.md, checkpoint-pointer.json}`.
  코어가 이미 일부 제공 (#2 evaluator-runner의 ledger.py/decision.py/evaluator.py + omx eval).
  checkpoint_pointer_json getter도 이미 존재 (omx_paths.py). 먼저 뭐가 있고 뭐가 없는지 recon.
- **#2의 미뤄둔 Minor NaN 가드**도 여기서 처리 (omx eval non-finite score -> allow_nan=False;
  HANDOFF.md line ~17 참조 — 이미 _cmd_eval엔 들어갔을 수 있으니 grep으로 현 상태 확인).

워크플로우: superpowers writing-plans -> subagent-driven-development (검증된 #3/#4/#5 패턴).
- task별 fresh implementer(sonnet) -> spec 리뷰(haiku) -> quality 리뷰(sonnet) -> 통과 시 다음
  -> 전체 끝나면 opus 최종 리뷰 -> finishing-a-development-branch.
- plan 쓰기 전 ground-truth recon 필수:
  (a) 코어에 이미 있는 것 (ledger.py/decision.py/evaluator.py/omx eval/checkpoint_pointer_json
      getter)의 시그니처 + 무엇이 빠졌는지,
  (b) exp-analyze report.md + exp-design proposal.md 포맷 (루프가 둘을 어떻게 엮는지),
  (c) autoresearch 루프 원본 (OMC marketplaces/omc/src/autoresearch/{contracts,runtime}.ts —
      keep-policy/decision-log/max-runtime ceiling),
  (d) #2 NaN 가드의 현 상태 (omx eval _cmd_eval에 allow_nan=False 있는지 grep).

제약 (반드시 지킴):
- 훈련/eval 자동발사 절대 금지 — exp-loop은 다음 launch를 pending-approval로 큐잉만. 새 훈련 launch 없음.
- omx-core의 Claude-free 부분은 Claude-free 유지. 루프 오케스트레이션 판단 = 스킬(Claude),
  ledger/decision/eval IO = 코어(파이썬). 경계 안 흐림.
- 1-GPU 순차 가정 (design §9): autoresearch sequential 기본. nvidia-smi 게이트는 launch 큐잉 시 명시.
- 절대경로/private repo명 박지 말 것 (public repo). placeholder.
- 커밋은 중요 변화마다 자동, 메시지 끝 Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>.
- push는 유저 명시 요청 시만 (현재 #5까지 10 commits 미push 상태 — #6도 승인 전엔 local merge까지만).
- 작업 끝나면 plugin.json skills:[]에 exp-loop 등록 (현재 3개: exp-init/exp-analyze/exp-design).
- 응답은 한국어. 코드/주석/마크다운은 영어. 이모지 금지. AI-attribution 텍스트 금지(git 트레일러는 예외).
```

---

## 현재 상태 (요약) — compact 후 이거 먼저 보면 됨

### 완료 (엔진 + 배포 + 스킬 3개)
- **#0/#1/#2** = 엔진 (paths/ingest/reduce/cli/evaluator-runner/ledger/decision). main 병합 + push.
- **#3 exp-init** = 인터뷰 -> profile bootstrap. main 병합 + push.
- **#4 exp-analyze** = hybrid PNG-vision 분석 + WandB/TB 어댑터 실구현. main 병합 + **push** (`43963f9`).
- **#5 exp-design — DONE + MERGED-local (NOT pushed)**: 코어 `report.py`/`parse_findings` +
  `omx report-parse` verb (Claude-free, malformed 태그 loud-fail) + `skills/exp-design/SKILL.md`
  (3-lane 진단 -> discriminating probe -> `proposals/<TS>-next.md` pending-approval, 훈련발사 금지).
  기존 `proposal_md`+`atomic_path` 재사용 (새 코어 path 코드 0). **292 passed/1 skipped.**
  FINAL opus=MERGE_READY. merge `b39944d` no-ff, **local main이 origin보다 10 ahead — 미push**
  (유저가 "local merge"만 선택, push 미승인).

### 미완 (= 다음 세션들)
- **스킬 1개 미구현**: exp-loop(#6, 다음). 그 후 #7 마무리.
- **plugin.json skills**: 현재 3개. #6 끝나면 exp-loop 추가 = 4개 (design의 4-skill 셋 완성).
- **미push**: build #5 10 commits. 유저 "push해줘" 시 origin/main 반영 (claudebase가 마켓플레이스
  버전핀 없이 추적 -> 새 skill 자동배포, claudebase 수정 불필요, #4와 동일).
- **legitimate deferral** (갭 아님): `tables/` 출력 트리(`analysis_table` getter 미사용, future hook).

### 남은 build 순서 (design §8 DAG)
```
#6 exp-loop   <- 다음 (analyze->design->eval 자율 루프 + 훈련 launch 큐잉 + #2 NaN 가드)  [이 세션]
#7 plugin.json skills 최종 + 완성
```

### 환경 함정 (HANDOFF.md 상세, 핵심만)
- `python` = Isaac 래퍼 -> 반드시 `python3` (3.12.3, pytest 9.x).
- `pip install -e .` -> `--break-system-packages` 필요.
- dist dir = `omx-core/`(하이픈), import pkg = `omx_core/`(언더스코어). cache = `.npz`.
- Pyright `reportMissingImports`(omx_core.*) + protobuf dynamic-attr = 전부 editable/false positive, 무시.
- 백그라운드 subagent에 SendMessage로 review-fix 시 완료 알림이 1턴 늦을 수 있음 -> 깨어나면 git log로 실제 상태 먼저 확인.
- 리뷰어 프롬프트엔 추측 SHA 금지, implementer 완료 후 git log로 실제 SHA 확인해 전달.
- **ScheduleWakeup 재예약 prompt 주의**: 이 파일/wakeup prompt가 옛 빌드를 가리키면 글자 그대로 실행 말 것
  — 먼저 git log + HANDOFF로 실제 완료 상태 확인 후, 진짜 미완 작업만 진행 (2026-05-30 #5에서 옛 T3-polish
  wakeup이 #5 완료 후 도착해 재시작 유발할 뻔함).
```
