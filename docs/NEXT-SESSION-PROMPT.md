# OMX 다음 세션 시작 prompt — build #8 `workspace-wiki` **구현** (brainstorm+plan 완료, 구현만 남음)

> 이 파일을 다음 세션에 "이 파일 읽고 시작해"로 지시하면 됨.
> 작성: 2026-05-31 (build #8 brainstorm+plan 완료 직후, 구현 전 compact 직전).
> HEAD = main `4dfb848`. origin/main 대비 **25 commits ahead, NOT pushed** (#5+#6+#8-docs — push 미승인).

---

## 지금 어디까지 왔나 (한눈에)

OMX v0.1 스킬셋 4개 완성 (exp-init/analyze/design/loop). 코어 316 passed/1 skipped.
**build #8 workspace-wiki = brainstorm + plan 끝. 남은 건 구현뿐.**

- **Spec (승인됨)**: `docs/superpowers/specs/2026-05-31-omx-workspace-wiki-design.md` (결정 W1-W8 + §0.1 INV-1/INV-2)
- **Plan (작성+self-review 완료)**: `docs/superpowers/plans/2026-05-31-omx-workspace-wiki.md` (T1-T11 + FINAL, bite-sized TDD, 완전한 코드)

남은 build: **#8 구현** (이번) → 그 후 **#7 finalize/deploy** (#8 후).

---

## 이번 세션 = build #8 구현 (subagent-driven-development)

### 바로 시작: plan을 task별로 실행
**brainstorm/plan 단계는 끝났다. 다시 brainstorm 하지 말 것.** `superpowers:subagent-driven-development`로
`docs/superpowers/plans/2026-05-31-omx-workspace-wiki.md`를 T1부터 순서대로:
- task별 fresh implementer(sonnet) → spec 리뷰 + quality 리뷰 → 통과 시 다음 → 전체 끝나면 opus FINAL(7 렌즈) → finishing-a-development-branch(local main, **push 안 함**).
- 검증된 #0~#6 패턴. 각 task = 1 commit, git 트레일러 필수, 풀 스위트 매 task 후 실행(카운트는 오르기만).

### 무엇을 만드나 (plan 요약 — 상세는 plan 파일)
`omx_core/wiki/` 4분할(Claude-free, time-injected): types/storage/ingest/query/lint = OMC wiki를 Python으로 재구현(import 아님).
+ `omx wiki add/query/lint/list` CLI verbs + `omx_paths` wiki getters(finding/registry_index 제거) + 4 스킬 통합(init seed / analyze query+add via `--from-report` / design query / loop lint).
**임베딩 절대 금지. 새 skill 없음(plugin.json 4개 유지).**

### 잠긴 결정 (재논의 금지 — spec §0)
- W1 Full parity 코어(storage/ingest/query/lint) · W2 경계: 코어=순수 결정론 IO/검색/감사(now 주입), Claude=무엇·어떤 category 판단 · W3 registry/ 재설계(findings=pages+index.md+log.md+.wiki-lock) · W4 add 주흐름 + `--from-report` 추출전용 모드 · W5 lint verb+exp-loop 호출(보고만) · W6 seed=인터뷰 산출물 1 page · W7 approach A 4모듈 · W8 corrupt-page=skip+corrupt_pages[] 보고.
- **INV-1 범용성**: 코어에 도메인 지식 0(isaaclab/uuv/metric명/절대경로/private repo명 금지). **INV-2 특화**: 특화는 데이터(.omx/registry/ pages)에 누적, append-only merge, CJK bigram 한국어 검색.

### 먼저 읽어라 (순서대로)
1. `docs/superpowers/plans/2026-05-31-omx-workspace-wiki.md` — **이게 실행 대본**. T1-T11 완전한 코드.
2. `docs/superpowers/specs/2026-05-31-omx-workspace-wiki-design.md` — 결정 근거(왜 그렇게).
3. `docs/HANDOFF.md` — 현재 상태.
4. (필요 시) OMC wiki 소스 `/root/.claude/plugins/marketplaces/omc/src/hooks/wiki/{types,storage,query,ingest}.ts` — 재구현 원본(이미 plan에 코드로 반영됨).
5. 메모리 `omx-build8-workspace-wiki-2026-05-31`(있으면) / `omx-build6-exp-loop-2026-05-30`.

### 제약 (반드시 지킴)
- **brainstorm/plan 재실행 금지** — 이미 끝남. 바로 subagent-driven 구현.
- 임베딩 금지. 코어 Claude-free(now 주입). path-SSOT(omx_paths getter만). 절대경로/private repo명 금지.
- `python3`(NOT `python`=Isaac). dist `omx-core/`(하이픈) vs pkg `omx_core/`(언더스코어). `pip install -e .`→`--break-system-packages`.
- 테스트: `cd /workspace/oh-my-experiments/omx-core && python3 -m pytest tests/ -q` (baseline 316 passed/1 skipped).
- 커밋 자동(task별), 트레일러 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. push는 유저 명시 요청 시만(현재 25 미push). 응답 한국어, 코드/마크다운 영어, 이모지 금지, AI-attribution 금지(트레일러 예외).
- stage는 명시 경로만(`git add <paths>`), `git add -A` 금지(동시세션).

### 환경/검증 함정
- plan은 cli.py/`__init__.py`/test 구조 대비 검증됨: cli.py에 `json/sys/datetime,timezone/parse_findings` 이미 import(T9에서 중복 말 것), `Path`는 implementer가 확인. `__init__.py` line 16-26 `__all__`에 append. `test_core_import_safe.py`의 `test_loop_symbols_exported` 패턴을 wiki로 복제(T8).
- 백그라운드 subagent SendMessage review-fix → 알림 1턴 늦을 수 있음 → 깨어나면 git log로 실제 상태 먼저 확인.
- **ScheduleWakeup/옛 prompt 주의**: 이 파일이 옛 단계를 가리키면 글자대로 실행 말 것 — git log + HANDOFF로 실제 완료 상태 확인 후 진짜 미완만 진행.

---

## #7 (나중에 — #8 구현 후) 메모: 배포 시 claudebase pull-first
#7 배포에서 claudebase 등록(settings.json + install.sh) **직전 반드시 `git pull` claudebase** (유저 지시 2026-05-30, memory `claudebase-pull-before-register`). omx repo public-flip + push 3곳은 outward-facing/비가역 → 실행 직전 1줄 confirm.
