# OMX 작업 핸드오프 (2026-05-30, compact 시점)

> 다음 세션/compact 이후: 이 파일 + `docs/design/2026-05-30-omx-experiment-harness-design.md`(진실원) +
> `docs/superpowers/plans/2026-05-30-omx-paths.md`(실행 계획)만 읽으면 이어서 작업 가능.

## 현재 상태 (요약)

레포 `/workspace/oh-my-experiments`, 작업 브랜치 **`feat/omx-paths`** (main 아님 — main=검증된 원본).
**push 안 함** (유저 명시 요청 시에만). working tree clean.

### 완료된 것
1. **설계 검토** — 5차원 ground-truth 리뷰(OMC 4.14.4 소스 대조) → blocker 8개(B1~B8) 발견·해결.
   design doc §0.1(해결표) + §4.1(exp-init 토폴로지) + §11(MCP 분석) 추가. 커밋 `3de0790`.
   - MCP 질문 답: 자립도 공유도 안 함, D3(서버 없음) 유지 (§11).
2. **TDD 계획** — `omx_paths.py`(build-order #0)를 6 task로 분해. 커밋 `d10ac48`.
3. **build-order #0 `omx_paths.py` 구현 — 6 task 전부 DONE + 2단 리뷰(spec→quality) 통과 + opus 최종 리뷰 ✅ MERGE-READY.**

### omx_paths.py 커밋 체인 (feat/omx-paths, main보다 6 커밋 앞섬)
- `612cfbc` task1: 패키징 + OmxPathError
- `39169ac` task2: validators + Profile (newline-injection 방어 `\A\Z` + regex compile)
- `b9c51e4` task3: OmxPaths .omx/ getters + 2-tier 검증 (traversal-safe)
- `8c3a626` task4: 영구 output-tree getters + vocab tier
- `46ddb5b` task5: resolve_session_id(B2) + atomic_path/atomic_dir (leak-fix)
- `489df5e` task6: getter-coverage guard + .gitkeep 청소

**검증:** `cd omx-core && python3 -m pytest tests/ -q` → **110 passed**. 순수 stdlib, Claude/Isaac 0 의존.
모듈 328줄 + 테스트 526줄. opus 리뷰: Critical/Important 0, Minor 3(전부 의도된 deferred).

### 다음에 할 일
**A. 브랜치 마무리 결정 (finishing-a-development-branch):** merge to main / PR / keep / discard 중 택1.
   - 권장: opus가 MERGE-READY 판정 → main merge 또는 PR. (push는 유저 허가 후)
**B. build-order 계속 (design §8 수정된 DAG):**
   - #1 omx-core skeleton: ingest 어댑터 + reduce(summary-stat/downsample/plot) + .omx state schema. Claude-free={ingest,reduce,eval}.
   - #2 evaluator-contract runner + Isaac Lab **reference** profile (커밋된 reference, score-optional/pass_only, B5/B6 결정 반영).
   - #3 exp-init (토폴로지 §4.1 저작됨) → profile 작성.
   - #4 exp-analyze (PNG-vision, Claude-required).
   - #5 exp-design (trace 3-lane → probe).
   - #6 exp-loop (autoresearch loop, 퇴근토글=분석/설계만 자동·훈련 launch는 큐잉 B8).
   - #7 cards/omx.json + omha 등록 + claudebase installer.
   - 각 build-order는 별도 writing-plans → subagent-driven-development(이번과 동일 패턴).

### #0이 다음 task에 남긴 단 하나의 숙제 (opus Minor)
**H4 root 자동탐색 미구현(의도된 deferred).** `OmxPaths(root=...)`는 root를 명시 인자로 요구.
   "cwd/nearest repo root 탐색 + OMX_ROOT env" 규칙은 #1/exp-init/CLI가 소유 → 호출자가 resolve해서 넘겨야 함.
   (`validate_ext`는 export됐지만 아직 미사용 getter — #1+ 대비 forward helper. `analysis_id`는 구조검증만, 달력검증 아님.)

## 환경 함정 (이미 데인 것들)
- `python` = Isaac Sim 래퍼. **반드시 `python3`** (3.12.3 + pytest 9.0.2).
- `pip install -e .`는 PEP 668 → `--break-system-packages` 필요 (root Docker, 안전).
- Pyright `reportMissingImports`는 editable 패키지 false positive — 무시 (프로젝트 gotchas 룰).
- 배포 dir = `omx-core/`(하이픈), import 패키지 = `omx_core/`(언더스코어).
- `AskUserQuestion`이 이 환경에서 guard 훅 누락으로 실패 → 결정은 prose 권장안+진행으로 대체.
- 이번 세션 tool 출력이 종종 1턴 늦게 렌더됨(transport 지연, state 손상 아님) — 재호출 전 다음 턴 확인.

## subagent-driven 실행 패턴 (검증됨, 재사용)
task별 fresh implementer(sonnet) 디스패치 → spec 리뷰(haiku) → quality 리뷰(sonnet) → 내가 fix 판정.
**핵심 교훈:** quality 리뷰에 항상 "newline/`$` 앵커 + path-traversal" 명시 지시 (실제 버그 거기서 잡힘).
agent 발견은 코드로 재검증 후 수용 (C1 newline은 내 오진이었고 live 체크로 기각함).

## 잠긴 설계 결정 (재논의 금지 — design §0.1)
B1 2-tier 검증 / B2 session_id(flag→env→autogen) / B3 report.md 영구트리 단일홈+plot promotion /
B4 DAG(exp-init #3, evaluator #2=reference profile) / B5 score pass_only선택·score_improvement필수 /
B6 revert=config git+checkpoint 포인터 / B7 card url 선언적 / B8 훈련 launch 자동발사 금지(큐잉).
