"""program-lint: the escalation gate on programs/<id>/PLAN.md.

Every case here is a shape the 2026-08 dgx-final-scaleup plan actually had, or
the shape it should have had. That plan named a knob under a tier titled "a
decision is required", resolved it internally against measurement readability,
never listed it for the user, and cost 11x the compute of its reference to land
2% away from it.
"""
from omx_core.cli import main
from omx_core.program import PLAN_TEMPLATE, lint_program

WELL_FORMED = """# Program: p
## Objective
> train for the best performance you can get

## Parameter coupling
### Tier 2 — real coupling; a decision is required
| step_interval | 250 | (a)/(b) | max_iterations | `[DECISION-REQUIRED: step-interval]` |

## Decisions for the user
- `[DECISION-REQUIRED: step-interval]` (a) saturates early then idles, (b) dwells
  3x longer per level. Recommend (b); (a) costs ~12k frozen-DR iterations.

## Predicted outcome
Equivalent to the 4096-env reference unless the DR bounds widen.
"""


def _rules(text):
    return {i["rule"] for i in lint_program(text)["issues"]}


def test_well_formed_plan_passes():
    assert lint_program(WELL_FORMED)["ok"] is True


def test_template_passes_its_own_lint():
    """A seeded skeleton must not fail structurally — authors edit, not rebuild."""
    assert lint_program(PLAN_TEMPLATE.format(program_id="p"))["ok"] is True


def test_empty_plan_reports_every_missing_section():
    assert _rules("# Program: p\n") == {
        "objective-missing", "decisions-section-missing", "predicted-outcome-missing"}


def test_paraphrased_objective_is_rejected():
    """A restated objective drifts; a drifted objective makes every trade look right."""
    text = WELL_FORMED.replace("> train for the best performance you can get",
                               "The user wants good performance.")
    assert "objective-not-verbatim" in _rules(text)


def test_marked_decision_missing_from_the_list_fails():
    """THE incident: the plan declares a decision necessary, then takes it."""
    text = WELL_FORMED.replace(
        "- `[DECISION-REQUIRED: step-interval]` (a) saturates early then idles, (b) dwells\n"
        "  3x longer per level. Recommend (b); (a) costs ~12k frozen-DR iterations.",
        "- (nothing escalated)")
    assert "decision-not-escalated" in _rules(text)


def test_slug_matching_is_normalized():
    """`step_interval` in the tier and `step-interval` in the list are the same knob."""
    text = WELL_FORMED.replace("[DECISION-REQUIRED: step-interval]",
                               "[DECISION-REQUIRED: step_interval]", 1)
    assert "decision-not-escalated" not in _rules(text)


def test_populated_tier2_without_any_marker_fails():
    """The hole a marker-only rule leaves: found the coupling, marked nothing."""
    text = WELL_FORMED.replace("`[DECISION-REQUIRED: step-interval]`", "held")
    assert "tier2-unmarked" in _rules(text)


def test_prose_claiming_a_decision_is_required_must_be_marked():
    text = WELL_FORMED.replace("## Predicted outcome",
                               "## Analysis\nThe kl_ub row requires a decision.\n\n"
                               "## Predicted outcome")
    assert "decision-phrase-unmarked" in _rules(text)


def test_korean_decision_phrase_is_caught():
    """These plans are authored bilingually; the trigger words are functional data."""
    text = WELL_FORMED.replace("## Predicted outcome",
                               "## 분석\nkl_ub 행은 결정이 필요하다.\n\n"
                               "## Predicted outcome")
    assert "decision-phrase-unmarked" in _rules(text)


def test_tier_heading_itself_is_not_flagged():
    """'### Tier 2 — a decision is required' is a section label, not an unmarked claim."""
    assert "decision-phrase-unmarked" not in _rules(WELL_FORMED)


def test_decision_list_may_discuss_decisions_freely():
    text = WELL_FORMED.replace("## Predicted outcome",
                               "x\n- a decision is required on the eval cadence too\n\n"
                               "## Predicted outcome")
    assert "decision-phrase-unmarked" not in _rules(text)


def test_cli_returns_2_on_issues_and_0_when_clean(tmp_path, capsys):
    good = tmp_path / "PLAN.md"
    good.write_text(WELL_FORMED)
    assert main(["program-lint", "--path", str(good)]) == 0

    bad = tmp_path / "BAD.md"
    bad.write_text("# Program: p\n")
    assert main(["program-lint", "--path", str(bad)]) == 2
    assert "objective-missing" in capsys.readouterr().out


def test_cli_loud_fails_on_a_missing_file(tmp_path, capsys):
    """main() intercepts SystemExit(str) and maps it to rc 2 with the message on stderr."""
    assert main(["program-lint", "--path", str(tmp_path / "nope.md")]) == 2
    assert "cannot read" in capsys.readouterr().err


# --- tier1-held-key-rescaled (the 2026-08 dgx-final-teacher Arm D incident) ---
#
# `num_envs` 4096 -> 16384 while the DORAEMON knobs it feeds kept their 4096
# values. The plan's own tier-1 table printed "boundaries fired 80 -> 40" under
# "nothing to set". The number was computed, displayed, and never argued.

RESCALED = """# Program: p
## Objective
> train the final teacher

## Parameter coupling
### Tier 1 — follows mechanically; nothing to set
| quantity | Arm W (4096) | Arm D (16384) |
|:--|--:|--:|
| boundaries fired (`max_iterations` / `step_interval`) | 80 | 40 |

### Tier 3 — no coupling that this plan moves; byte-identical
`step_interval` 250 (the dwell window); `gamma`/`lam` 0.99/0.95.

## Decisions for the user
- (nothing escalated)

## Predicted outcome
Equivalent to the 4096-env reference.
"""


def test_held_key_whose_meaning_moved_is_flagged():
    assert "tier1-held-key-rescaled" in _rules(RESCALED)


def test_derived_assertion_clears_the_row():
    """The author types the assertion; the gate is satisfied by an argument."""
    assert "tier1-held-key-rescaled" not in _rules(
        RESCALED.replace("| 80 | 40 |", "| 80 | 40 | [DERIVED]"))


def test_escalating_the_row_also_clears_it():
    text = RESCALED.replace("| 80 | 40 |", "| 80 | 40 | [DECISION-REQUIRED: dwell]"
                            ).replace("- (nothing escalated)",
                                      "- `[DECISION-REQUIRED: dwell]` re-derive step_interval at 16384")
    assert "tier1-held-key-rescaled" not in _rules(text)


def test_unmoved_row_is_not_flagged():
    """A held key in a row whose value did NOT move is exactly tier 1's job."""
    assert "tier1-held-key-rescaled" not in _rules(
        RESCALED.replace("| 80 | 40 |", "| 80 | 80 |"))


def test_key_not_held_in_tier3_is_not_flagged():
    """Only the value-held-meaning-moved shape; a moving knob is tier 2's problem."""
    assert "tier1-held-key-rescaled" not in _rules(
        RESCALED.replace("`step_interval` 250 (the dwell window); ", ""))
