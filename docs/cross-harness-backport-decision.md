# Cross-harness backport 판정 — omp 0.2.0 → omx (2026-05-31, 채택 0)

> 코드 변경 없음(NO-OP). 이 파일은 *판정의 영속 기록*일 뿐 — 다음 세션이 같은 검토를
> 반복하지 않도록 남긴다.

형제 **omp(oh-my-project) 0.2.0** 이 추가한 5종을 omx 로 backport 할지 적대 검증
(propose↔refute, 2026-05-31)으로 따졌다. **결과: 5후보 전부 REJECT, 채택 0.**

| omp 0.2.0 후보 | omx 판정 | 사유 |
|:---|:---|:---|
| `content_conventions[]` 규칙 타입 | REJECT | omx 에 rules.json·audit PASS/FAIL gate·specificity 가 전무. 이식은 backport 가 아니라 규칙 엔진 골격 신규 설계 → over-engineering. |
| content audit 축 (`check_content_rule`) | REJECT | 규칙 엔진 호출자(auditor) 자체 부재. omx 의 검증은 통계적 정직성 rubric(가설검정·p-hacking 회피·음성결과 보고)이지 정규식 body 규칙이 아님. |
| dead-link (`find_dead_links`) | REJECT | **중복** — `omx-core/omx_core/wiki/lint.py` 가 broken-ref 를 이미 보유하고, 거기에 orphan/stale/oversized/broken-frontmatter 까지 더한 **상위집합**. omp dead-link 가 오히려 이 lint 보다 약하다. |
| `.omp/CONVENTIONS.md` | REJECT | content_conventions[] 의 prose mirror — 비출 머신 규칙(rules.json)이 omx 에 없어 빈 문서가 됨. body 품질은 lint.py 가 이미 기계화. |
| specificity content 항 | REJECT | omx 엔 specificity 공식 자체가 없어 삽입점 0. substrate(rules.json+audit+specificity) 통째 이식 필요 → 신규 설계. |

## 왜 omx 는 구조적 비대상인가

1. **self-contained 설계** (README): "zero runtime dependency on OMC, immune to OMC version
   changes, re-implements patterns in its own code." omx 는 OMC 든 형제든 *외부 패턴을 직접
   import 하지 않고* 자기 코드로 재구현하는 것이 정체성. 형제 backport 를 받는 모델이 아니다.
2. **도메인 비대칭**: omp = 살아있는 `.omp/` 를 rules.json 정규식으로 반복 재검사하는 *관리 루프*.
   omx = exp-init/analyze/design/loop 의 *생성·분석 파이프라인*. omp 5종이 깔고 있는 "기존 파일
   body 를 규칙으로 재스캔" 전제가 omx 엔 없다(의도된 부재, 결함 아님).
3. **인접 기능 이미 보유**: 파일 위생 검사는 `omx-core/wiki/lint.py` 가 omp 보다 강하게 충당.

이는 2026-05-31 omx wiki 대조분석(6후보 중 5 REJECT, 유일 ADOPT 도 코드 0줄 "문장만")과 동형이며,
사용자 지침("무리하게 backport 하지 말 것, 진짜 가치있는 것만")에 부합한다.

**결론: omp 0.2.0 → omx 채택 0. omx 코드는 그대로 둔다.**
(형제 oms/omd 도 동일 결론 — 각 `references/omc-backport-analysis.md` §4 참조.
 omp 의 종합 기록은 omp `references/omc-backport-analysis.md` §5.)
