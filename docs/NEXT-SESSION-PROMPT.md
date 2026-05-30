# OMX 다음 세션 시작 prompt — build-order #3 `exp-init` skill

> 이 파일을 다음 세션에 그대로 붙여넣거나, "이 파일 읽고 시작해" 라고 지시하면 됨.
> 작성: 2026-05-30 (build #2 배포 완료 직후). HEAD 기준 origin/main 동기화 상태에서 작성 (현재 최신 커밋부터 이어서).

---

## 붙여넣을 prompt (이 블록만 복사해도 됨)

```
OMX build-order #3 (exp-init skill) 진행. ew opus.

먼저 읽어라 (순서대로):
1. docs/HANDOFF.md — 현재 상태 + 환경 함정
2. docs/design/2026-05-30-omx-experiment-harness-design.md
   §4 (4 skills 표) + §4.1 (exp-init 인터뷰 토폴로지 — 이게 #3의 spec) + §10 (.omx/ 디렉토리 규율, H4 root) + §8 #3
3. 메모리 project-omx-harness-2026-05-30 (이미 컨텍스트에 로드됨)

작업: design §4.1 그대로 exp-init 스킬을 구현.
- exp-init = "research /init" — deep-interview ambiguity-gate를 재사용한 인터랙티브 Socratic 인터뷰.
  5개 실험 토픽(objective/metrics/eval-method/success-criteria/launch-recipe)을
  deep-interview의 3차원(Goal 0.40 / Constraints 0.30 / Criteria 0.30)에 매핑(§4.1 표).
- 산출물: .omx/profile/{evaluator.sh, metrics.yaml, rules.md, launch.sh}, "pending approval" 라벨.
- H4 부트스트랩: .omx/는 cwd(또는 enclosing repo root)에 고정, output_root는 metrics.yaml 안에 저장
  (omx_paths.py가 .omx/ root를 output_root와 독립적으로/먼저 resolve — §10.1).
- 인터뷰는 인터랙티브(매 라운드 사람이 답함, H2 — 자율 아님). exp-loop만 toggle-autonomous.

워크플로우: superpowers writing-plans → subagent-driven-development (HANDOFF.md "subagent-driven 실행 패턴" 따름).
- 스킬 spec이 §4.1에 이미 authored됨 (H1 해결) → 재설계 불필요, 바로 plan 가능.
- 단 SKILL.md를 처음 쓰는 거라, omx-core CLI(omx ingest/reduce/eval)를 스킬이 어떻게 호출하는지 +
  profile 파일 4종의 정확한 스키마는 plan 단계에서 확정할 것.

제약 (반드시 지킴):
- 훈련 launch 자동발사 절대 금지 (D4/B8) — exp-init은 profile만 만들고 아무것도 실행 안 함.
- omx-core는 Claude-free 유지 — 스킬(Claude)과 코어(파이썬)의 경계 안 흐림.
- 절대경로/private repo명 박지 말 것 (public repo, 배포물). placeholder 사용.
- 커밋 메시지 끝: Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
- push는 유저 명시 요청 시만. 작업 끝나면 plugin.json skills:[] 에 exp-init 등록(#7 점진).
- AskUserQuestion이 이 환경에서 깨짐(guard 훅 없음) → prose 권장안+진행.
```

---

## 다음 세션이 알아야 할 현재 상태 (요약)

### 완료 (엔진 + 배포)
- **#0 omx_paths.py / #1 omx-core skeleton / #2 evaluator runner** = 전부 merged to main. 223 tests pass / 1 skip.
- `omx` CLI 4 verb 동작: `ingest` / `reduce` / `session-id` / `eval`. 순수 파이썬, Claude-free.
- **배포 완료**: omx repo PUBLIC, 자체 `omx` marketplace, heroacademia 3-lane 카드(cards/omx.json), claudebase 등록(settings+installer). 3 repo 전부 push됨.
- **omha 라우팅 통합 = 됨** (카드 인식, 레인 주입, verdict enum). 라이브 검증됨.

### 미완 (= 이 세션부터 지을 것)
- **스킬 4개 전부 미구현** (SKILL.md 0개): exp-init(#3, 다음) → exp-analyze(#4) → exp-design(#5) → exp-loop(#6).
  - **이게 omha 통합의 "실행 레벨" 갭** — 라우터가 OMX 레인으로 보내도 호출할 스킬이 없음. exp-init이 첫 스킬.
- **ingest stub 2개**: WandbAdapter / TensorboardAdapter (`omx_core/ingest/stubs.py`, NotImplementedError) → #4 exp-analyze에서 실데이터로 구현.
- **미정 (build 시점에 확정)**: score formula(D5, exp-init이 profile별 elicit) / exp-loop revert 스키마(B6 ledger.json 포인터) / profile 부트스트랩(exp-init이 생성).
- **plugin.json `skills: []`** — 스킬 구현될 때마다 채움(#7 점진적).

### 남은 build 순서 (design §8 DAG)
```
#3 exp-init   ← 다음 (인터랙티브 인터뷰 → profile)   [이 세션]
#4 exp-analyze (PNG-vision 분석, Claude 필수, WandB/TB 어댑터 실구현)
#5 exp-design  (trace 3-lane 진단 → 다음실험 제안)
#6 exp-loop    (자율 루프 + 퇴근토글, 훈련 자동발사 금지)
#7 plugin.json skills 채우기 + 완성
```
각 스킬 = 큰 작업, 한 세션에 하나씩. 각각 fresh writing-plans → subagent-driven.

### 환경 함정 (HANDOFF.md 상세, 핵심만)
- `python` = Isaac 래퍼 → 반드시 `python3` (3.12.3, pytest 9.x).
- `pip install -e .` → `--break-system-packages` 필요.
- dist dir = `omx-core/`(하이픈), import pkg = `omx_core/`(언더스코어).
- cwd 오염: `cd omx-core` 후 상대경로 재진입하면 깨짐 → 절대경로 또는 repo-root에서.
- Pyright `reportMissingImports`(omx_core.*) = editable false positive, 무시.
