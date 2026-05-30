# OMX 작업 핸드오프 (2026-05-30 세션 종료 시점)

> 다음 세션이 이 파일 + `docs/design/2026-05-30-omx-experiment-harness-design.md`(진실원) +
> `docs/superpowers/plans/2026-05-30-omx-paths.md`(실행 계획)만 읽으면 이어서 작업 가능.

## 지금 어디까지 했나

레포 `/workspace/oh-my-experiments`, 작업 브랜치 **`feat/omx-paths`** (main 아님 — main은 검증된 원본 보존).
origin보다 앞서 있음, **push 안 함** (유저 명시 요청 시에만).

### 완료
1. **설계 검토** — 5차원 ground-truth 리뷰(OMC 4.14.4 소스 대조) → blocker 8개(B1~B8) 발견·해결.
   설계 문서 §0.1(해결표) + §4.1(exp-init 토폴로지) + §11(MCP 분석) 추가. 커밋 `3de0790`.
2. **TDD 계획** — `omx_paths.py`(build-order #0)를 6 task로 분해. 커밋 `d10ac48`.
3. **실행 (subagent-driven-development 진행 중):**
   - **Task 1 (DONE+리뷰통과):** 패키징 + `OmxPathError`. 커밋 `612cfbc`. spec ✅ / quality ⚠️(notes only).
   - **Task 2 (구현됨, CRITICAL 수정 중):** 구조 validators + `Profile` frozen dataclass. 커밋 `72deeb9`.
     - quality 리뷰가 **C1 Critical** 적발: `^...$` 앵커가 trailing/embedded newline 통과시킴
       (`validate_run_id('evil\nrm')` 통과 = path-injection 구멍). + **I1**: `Profile.run_id_regex` 미검증.
     - **수정 디스패치함**: 5개 regex `^...$` → `\A...\Z`, newline/control-char reject 테스트 추가,
       `Profile.__post_init__`에서 `run_id_regex` 컴파일 검증. 기존 Task-2 커밋에 `--amend`.
     - **다음 세션 첫 할 일**: 이 수정이 실제 적용·검증됐는지 확인 →
       `python3 -m pytest omx-core/tests/ -v` 전부 통과 + 아래 live 체크가 raise 하는지 확인:
       `python3 -c "from omx_core.omx_paths import validate_run_id; validate_run_id('evil\nrm')"` → OmxPathError 떠야 정상.
       통과하면 Task 2 spec+quality 재리뷰 → 완료 처리 → **Task 3부터 계속**.

### 남은 것 (계획서 그대로)
- **Task 3:** `OmxPaths` 클래스 + `.omx/` getters (profile/runs/scratch/registry/state) + 2-tier 검증 배선.
- **Task 4:** 영구 output-tree getters (analysis/report/plots/tables/manifest/proposal) + vocab tier.
- **Task 5:** `resolve_session_id`(B2 우선순위) + `atomic_path`/`atomic_dir` + traversal property test.
- **Task 6:** 전수 getter-coverage 가드 + .gitkeep 청소 + import-from-anywhere 최종 점검.
  - Task 6에서 처리할 quality note 이월분: testpaths rootdir 주석(Note1), py.typed(Note3, 타입체커 게이트 넣을 때만).

### 재개 방법
TaskList가 비어있으면 계획서로 복원. subagent-driven-development skill 재호출 →
task별 fresh implementer 디스패치 + spec→quality 2단 리뷰 (이번 세션과 동일 패턴).
**핵심 교훈: quality 리뷰에 항상 "newline/`$` 앵커 + path-traversal" 명시 지시** — C1이 거기서 잡혔음.

## 환경 함정 (이미 데인 것들)
- `python` = Isaac Sim 래퍼. **반드시 `python3`** (3.12.3 + pytest 9.0.2).
- `pip install -e .`는 PEP 668 때문에 `--break-system-packages` 필요 (root Docker, 안전).
- Pyright `reportMissingImports`는 editable 패키지 false positive — 무시 (프로젝트 gotchas 룰).
- 배포 dir = `omx-core/`(하이픈), import 패키지 = `omx_core/`(언더스코어).
- `AskUserQuestion`이 이 환경에서 guard 훅 누락으로 실패 → 결정은 prose 권장안+진행으로 대체.

## 잠긴 설계 결정 (재논의 금지 — 설계 §0.1)
B1 2-tier 검증 / B2 session_id 소스(flag→env→autogen) / B3 report.md 영구트리 단일홈+plot promotion /
B4 DAG(exp-init #3, evaluator #2는 reference profile) / B5 score는 pass_only 선택·score_improvement 필수 /
B6 revert = config git + checkpoint 포인터 / B7 card url 선언적 / B8 훈련 launch 자동발사 금지(큐잉).
MCP: 자립도 공유도 안 함, D3(서버 없음) 유지 (§11).
