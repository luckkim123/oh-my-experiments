# OMX 다음 세션 시작 prompt — OMX v0.1 SHIPPED (post-v0.1 대기)

> 작성: 2026-05-31 (#7 finalize/deploy + 배포 검증 완료 직후).
> HEAD = main `d37eb1e` + 이후 docs 커밋. origin/main **synced (0 unpushed)**.

---

## 상태: OMX v0.1 COMPLETE

전 build-order(#0~#8) DONE + #7 finalize/deploy + 배포 검증 PASS. **새 요청 대기 상태.**

- 4-skill 셋(exp-init/analyze/design/loop) + Claude-free `omx` core + workspace-wiki(build #8) 전부 배포·검증됨.
- 등록 인프라(omha 카드+라우팅 / claudebase settings.json+install.sh / OMC v4.14.4 핀)와 OMX repo 본체 전부 origin push 완료.
- 배포 검증 end-to-end PASS: fresh clone → `pip install -e` → `omx` CLI 전 verb 실행 → wiki 4-verb(latin+CJK query / append-merge 무손실 / lint) → 4 skill discover. leak-scan 0건. 366 passed/1 skipped.

---

## post-v0.1 후속 작업 후보 (요청 시)

design `docs/design/2026-05-30-omx-experiment-harness-design.md` §9 open items:
- **score-formula 실프로필 elicit** (mean+λ·CV vs per-axis worst-case) — exp-init이 실제 과거-run 데이터로 D5 elicit.
- **1-GPU vs tournament** parallelism (exp-loop) — multi-GPU 생기면 self-improve tournament.
- **MCP 승격 트리거** — OMX가 interactive-iterative로 진화하면 self-built MCP(공유 OMC MCP는 영구 거부, D1).
- **legacy results 마이그레이션** — `/workspace/docs/results/` 스키마로 산재 결과 이관 (repo 룰 02-operations, owed).
- **실데이터 dogfood** — exp-init으로 실제 isaaclab/eval_dr 프로필 부트스트랩 후 exp-analyze 실런 검증.

## 제약 (이어질 경우)
- 응답 한국어, 코드/마크다운 영어, 이모지 금지, AI-attribution 금지(git 트레일러만 예외).
- push는 유저 명시 승인 게이트. claudebase 편집 시 `git pull` 먼저([[claudebase-pull-before-register]]).
- `python3`(NOT `python`). dist `omx-core/`(하이픈) vs pkg `omx_core/`(언더스코어). `pip install -e .`→`--break-system-packages`.
- 테스트: `cd omx-core && python3 -m pytest tests/ -q` (baseline 366 passed/1 skipped).

## 먼저 읽어라
1. `docs/HANDOFF.md` — v0.1 SHIPPED 기록 + 전 build-order 상세.
2. `docs/design/2026-05-30-omx-experiment-harness-design.md` — 진실원(§9 open items).
3. 메모리 `omx-build8-workspace-wiki-2026-05-31` (v0.1 SHIPPED).
