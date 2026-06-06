# Cross-harness backport decision — omp 0.2.0 → omx (2026-05-31, 0 adopted)

> No code change (NO-OP). This file is merely a *permanent record of the decision* — kept so the
> next session does not repeat the same review.

The 5 items added by sibling **omp(oh-my-project) 0.2.0** were evaluated for backport into omx via
adversarial verification (propose↔refute, 2026-05-31). **Result: all 5 candidates REJECTED, 0 adopted.**

| omp 0.2.0 candidate | omx decision | Rationale |
|:---|:---|:---|
| `content_conventions[]` rule type | REJECT | omx has no rules.json, no audit PASS/FAIL gate, and no specificity at all. Porting it would not be a backport but a from-scratch design of a rule-engine skeleton → over-engineering. |
| content audit axis (`check_content_rule`) | REJECT | The rule-engine caller (auditor) itself is absent. omx's verification is a statistical-honesty rubric (hypothesis testing, p-hacking avoidance, negative-result reporting), not a regex body rule. |
| dead-link (`find_dead_links`) | REJECT | **Duplicate** — `omx-core/omx_core/wiki/lint.py` already holds broken-ref, and on top of that adds orphan/stale/oversized/broken-frontmatter as well — a **superset**. omp's dead-link is actually weaker than this lint. |
| `.omp/CONVENTIONS.md` | REJECT | A prose mirror of content_conventions[] — since omx has no machine rules (rules.json) to reflect, it would become an empty document. Body quality is already mechanized by lint.py. |
| specificity content term | REJECT | omx has no specificity formula at all, so there is 0 insertion point. The whole substrate (rules.json+audit+specificity) would need to be ported → from-scratch design. |

## Why omx is structurally out of scope

1. **self-contained design** (README): "zero runtime dependency on OMC, immune to OMC version
   changes, re-implements patterns in its own code." omx's identity is to *not directly import external
   patterns* — whether from OMC or a sibling — but to re-implement them in its own code. It is not a
   model that receives sibling backports.
2. **Domain asymmetry**: omp = a *management loop* that repeatedly re-checks a living `.omp/` with
   rules.json regexes. omx = a *generation/analysis pipeline* of exp-init/analyze/design/loop. The
   premise that omp's 5 items rest on — "re-scan the body of existing files against rules" — does not
   exist in omx (an intended absence, not a defect).
3. **Adjacent capability already present**: file-hygiene checking is covered by `omx-core/wiki/lint.py`
   more strongly than omp.

This is isomorphic to the 2026-05-31 omx wiki comparative analysis (5 of 6 candidates REJECT, even the
sole ADOPT was 0 lines of code, "prose only"), and conforms to the user's directive ("don't backport
forcibly, only what is genuinely valuable").

**Conclusion: omp 0.2.0 → omx, 0 adopted. The omx code is left unchanged.**
(Siblings oms/omd reach the same conclusion — see each `references/omc-backport-analysis.md` §4.
 omp's consolidated record is in omp `references/omc-backport-analysis.md` §5.)
