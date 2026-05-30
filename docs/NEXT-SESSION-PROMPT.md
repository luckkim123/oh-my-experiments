# OMX 다음 세션 시작 prompt — build #8 `workspace-specialization wiki` (브레인스토밍부터)

> 이 파일을 다음 세션에 "이 파일 읽고 시작해"로 지시하면 됨.
> 작성: 2026-05-30 (build #6 exp-loop 완료 직후, compact 직전).
> HEAD = main `4d71760`. origin/main 대비 **22 commits ahead, NOT pushed** (#5+#6 전체 — push 미승인).

---

## 지금 어디까지 왔나 (한눈에)

OMX v0.1 스킬셋 **4개 전부 완성**: exp-init(#3) · exp-analyze(#4) · exp-design(#5) · exp-loop(#6).
plugin.json skills = 4개. 코어(omx_paths/ingest/reduce/cli/evaluator/decision/ledger/report/loop) 전부 구현+리뷰됨. **316 passed / 1 skipped.**

남은 build:
- **#7 finalize** (배포) — omha card + claudebase 등록 + omx repo public-flip + push 3곳. **outward-facing/비가역**. 유저가 **#8을 #7보다 먼저** 하기로 결정함(2026-05-30). #7은 #8 후에.
- **#8 workspace-specialization wiki** — **이번 세션 목표**. 아래.

---

## 이번 세션 = build #8: workspace-specialization wiki

### 무엇 / 왜
유저의 핵심 요구: "exp-init으로 workspace 구조를 파악해 기록하고, OMX를 **쓸수록 그 workspace에 점점 특화**되어 간다." 현재 설계엔 `.omx/registry/findings/<slug>.md` (flat keyword+tag 마크다운 store, grep-only, 임베딩 없음)가 **씨앗만** 있고 얕음. 이걸 **OMC-wiki식 키워드 인덱스 지식 레이어**로 승격하는 게 #8.

### 검증된 레퍼런스 (이미 recon함 — OMC wiki 소스)
`/root/.claude/plugins/marketplaces/omc/src/hooks/wiki/` (~8 파일): `storage.ts`(.omc/wiki/ 마크다운 페이지 + 자동 index.md + append-only log.md, 파일 mutex) · `query.ts`(**키워드 검색, 임베딩 명시적 금지** — tokenize는 Latin+숫자+**CJK bigram**이라 한국어 검색됨; tag>title>content 스코어링) · `types.ts`(페이지 frontmatter: title/tags/created/updated/**sources**(기여 세션)/links(상호참조)/**category**∈{architecture,decision,pattern,debugging,environment,session-log,reference,convention}/**confidence**∈{high,med,low}/schemaVersion) · ingest/lint/session-hooks.
설계 철학: Karpathy "LLM Wiki" — 세션 거칠수록 **compound(누적)**.

### 이번 세션의 순서 (중요 — #8은 새 설계 단위라 바로 구현 금지)
**#6과 다르다.** #6은 design에 이미 plan 재료가 있었지만, #8은 design §9가 "**needs its own brainstorm+plan**"이라 명시. 따라서:
1. **brainstorm 먼저** (`superpowers:brainstorming` 또는 `oh-my-claudecode:deep-interview`) — 설계 결정을 핀으로 박아라:
   - 스코프: OMX의 registry/findings를 *어디까지* OMC-wiki화? (frontmatter 스키마 / 자동 index.md+log.md / 키워드 query / ingest 훅 — 전부? 일부?)
   - 누가 쓰나: exp-init이 workspace 구조를 읽어 seed page를 쓰고, exp-analyze/design/loop이 매 run마다 category-tagged finding을 append하고, 다음 run이 누적 지식을 query — 이 4-skill 통합 지점을 정해라.
   - Claude-free 경계: OMC처럼 storage/ingest/query를 코어(파이썬, 결정론)로? query 스코어링은 코어, "무엇을 기록할지" 판단은 스킬(Claude)? (OMX의 기존 boundary 원칙 유지)
   - 임베딩 금지 유지(OMC hard constraint + OMX D1/D2 minimal-surface)? grep+키워드 스코어링으로 충분한가?
   - path-SSOT: 새 wiki 경로는 전부 `omx_paths` getter로. 기존 `registry_index()`/`finding(slug)` getter 재사용 + 확장?
2. **그 다음 `superpowers:writing-plans`** 로 TDD plan (`docs/superpowers/plans/2026-05-30-omx-workspace-wiki.md`).
3. **그 다음 `superpowers:subagent-driven-development`** (검증된 #0~#6 패턴: task별 fresh implementer sonnet → spec+quality 2단 리뷰 → opus FINAL → finishing-a-development-branch=local main, push 안 함).

### 먼저 읽어라 (순서대로)
1. `docs/HANDOFF.md` — 현재 상태 (#6 DONE bullet 포함)
2. `docs/design/2026-05-30-omx-experiment-harness-design.md` §8 #8 + §9 마지막 bullet(workspace-wiki 등록 내용) + §10.2 (`.omx/registry/` 현재 트리: INDEX.md + findings/<slug>.md) + §1 (OMC borrow 표의 cross-session memory 행)
3. OMC wiki 소스 `/root/.claude/plugins/marketplaces/omc/src/hooks/wiki/{storage,query,types}.ts` — 직접 읽어 스키마/검색 메커니즘 확인 (위 recon 요약은 출발점일 뿐)
4. 기존 4 스킬 `skills/{exp-init,exp-analyze,exp-design,exp-loop}/SKILL.md` — wiki를 어디서 seed/append/query할지 통합 지점 파악
5. 메모리 `omx-build6-exp-loop-2026-05-30` (이미 로드됨)

### 제약 (반드시 지킴)
- **새 설계 단위 = brainstorm/plan 먼저, 바로 구현 금지** (design §9 "needs its own brainstorm+plan").
- 임베딩 금지 유지 (OMC hard constraint, D1/D2). 키워드+태그+grep만.
- omx-core Claude-free 부분은 Claude-free 유지 (storage/query IO = 코어, "무엇을 기록·왜" 판단 = 스킬).
- path-SSOT — 모든 wiki 경로 `omx_paths` getter 경유. hand-write 금지.
- 절대경로/private repo명 박지 말 것 (public repo, placeholder).
- 커밋 자동(중요 변화마다), 메시지 끝 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- push는 유저 명시 요청 시만 (현재 22 commits 미push — #8도 승인 전엔 local까지만).
- 응답 한국어, 코드/주석/마크다운 영어, 이모지 금지, AI-attribution 금지(git 트레일러 예외).

### 환경 함정 (불변)
- `python3` (NOT `python`=Isaac 래퍼). dist `omx-core/`(하이픈) vs pkg `omx_core/`(언더스코어).
- `pip install -e .` → `--break-system-packages`. Pyright `reportMissingImports(omx_core.*)` = editable false-positive, 무시.
- 테스트: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/ -q` (baseline 316 passed/1 skipped).
- 백그라운드 subagent SendMessage review-fix → 알림 1턴 늦을 수 있음 → 깨어나면 git log로 실제 상태 먼저 확인.
- **ScheduleWakeup 재예약 prompt 주의**: 이 파일/wakeup이 옛 빌드를 가리키면 글자대로 실행 말 것 — git log + HANDOFF로 실제 완료 상태 확인 후 진짜 미완만 진행 (2026-05-30 #5/#6에서 옛 wakeup이 완료 작업 재시작 유발할 뻔함, 둘 다 git-log 확인으로 회피).

---

## #7 (나중에 — #8 후) 메모: 배포 시 claudebase pull-first
#7 배포에서 claudebase 등록(settings.json + install.sh) **직전 반드시 `git pull` claudebase** (유저 지시 2026-05-30, memory `claudebase-pull-before-register` — claudebase에 최근 변경 많아 local clone이 뒤처져 있음). omx repo public-flip + push 3곳은 outward-facing/비가역 → 실행 직전 1줄 confirm.
