import pytest
from omx_core.report import Finding, ReportParseError, parse_findings


def test_parse_single_triplet():
    text = (
        "## Analysis Results\n\n"
        "[FINDING] ss_error converged faster in run A than run B.\n"
        "[EVIDENCE: summary.json hard/roll/ss_error=0.21 vs 0.76]\n"
        "[CONFIDENCE: HIGH]\n"
    )
    out = parse_findings(text)
    assert len(out) == 1
    f = out[0]
    assert isinstance(f, Finding)
    assert f.claim == "ss_error converged faster in run A than run B."
    assert f.evidence == "summary.json hard/roll/ss_error=0.21 vs 0.76"
    assert f.confidence == "HIGH"


def test_parse_multiple_triplets_ignores_prose_and_images():
    text = (
        "# Report\n"
        "Some intro prose.\n\n"
        "[FINDING] Run B has a heavy tail in attitude error.\n"
        "[EVIDENCE: attitude__overlay.png shape, scratch plot]\n"
        "[CONFIDENCE: MED]\n\n"
        "![](plots/attitude__overlay.png)\n\n"
        "[FINDING] vx steady-state offset is within spec.\n"
        "[EVIDENCE: summary.json soft/vx/ss_error=0.009]\n"
        "[CONFIDENCE: HIGH]\n"
    )
    out = parse_findings(text)
    assert len(out) == 2
    assert out[0].confidence == "MED"
    assert out[1].claim == "vx steady-state offset is within spec."
    assert out[1].evidence == "summary.json soft/vx/ss_error=0.009"


def test_parse_empty_returns_empty_list():
    assert parse_findings("") == []
    assert parse_findings("# Just a heading\nno tags here\n") == []


def test_finding_without_evidence_loud_fails():
    text = "[FINDING] dangling claim with no evidence line.\n"
    with pytest.raises(ReportParseError):
        parse_findings(text)


def test_finding_with_bad_confidence_keyword_loud_fails():
    text = (
        "[FINDING] claim.\n"
        "[EVIDENCE: src]\n"
        "[CONFIDENCE: PROBABLY]\n"  # not HIGH|MED|LOW
    )
    with pytest.raises(ReportParseError):
        parse_findings(text)


def test_orphan_evidence_tag_loud_fails():
    text = "[EVIDENCE: src with no finding above it]\n"
    with pytest.raises(ReportParseError):
        parse_findings(text)


def test_orphan_confidence_tag_loud_fails():
    text = "[CONFIDENCE: HIGH]\n"
    with pytest.raises(ReportParseError):
        parse_findings(text)


def test_finding_followed_by_prose_instead_of_evidence_loud_fails():
    text = (
        "[FINDING] claim.\n"
        "some prose that should have been an evidence tag\n"
        "[CONFIDENCE: HIGH]\n"
    )
    with pytest.raises(ReportParseError):
        parse_findings(text)


def test_orphan_bad_confidence_keyword_loud_fails():
    # a misspelled-keyword confidence tag with no open finding must NOT be
    # silently dropped (it opens with [CONFIDENCE but isn't HIGH|MED|LOW)
    with pytest.raises(ReportParseError):
        parse_findings("[CONFIDENCE: BOGUS]\n")


def test_valid_finding_after_a_first_triplet_still_parses():
    # guard against the _ANY_TAG orphan check wrongly catching a real [FINDING]
    text = (
        "[FINDING] first.\n[EVIDENCE: a]\n[CONFIDENCE: HIGH]\n\n"
        "[FINDING] second.\n[EVIDENCE: b]\n[CONFIDENCE: LOW]\n"
    )
    out = parse_findings(text)
    assert len(out) == 2
    assert out[1].claim == "second." and out[1].confidence == "LOW"


# --- GAP 3: a [FINDING] whose claim wraps across multiple prose lines (normal
# readable report writing) must still parse: lookahead to the next [EVIDENCE:]
# within the block and join the wrapped claim lines, instead of requiring the
# evidence on the very next line. Caught live: the dr-harder teacher report.md
# had 6 multi-line [FINDING] blocks; --from-report printed 0 candidates + exit 2.


def test_multiline_finding_claim_joins_and_parses():
    text = (
        "[FINDING] roll/pitch steady-state error grows sharply from none->hard while all\n"
        "translational axes (vx/vy/vz/yaw) stay near-zero across every DR level.\n"
        "[EVIDENCE: summary.json roll ss_error none 0.55 -> hard 1.10]\n"
        "[CONFIDENCE: HIGH]\n"
    )
    out = parse_findings(text)
    assert len(out) == 1
    f = out[0]
    # the two prose lines are joined into one claim (single space at the wrap)
    assert f.claim == (
        "roll/pitch steady-state error grows sharply from none->hard while all "
        "translational axes (vx/vy/vz/yaw) stay near-zero across every DR level."
    )
    assert f.evidence == "summary.json roll ss_error none 0.55 -> hard 1.10"
    assert f.confidence == "HIGH"


def test_multiline_finding_three_wrap_lines():
    text = (
        "[FINDING] line one\n"
        "line two\n"
        "line three\n"
        "[EVIDENCE: src]\n"
        "[CONFIDENCE: MED]\n"
    )
    out = parse_findings(text)
    assert len(out) == 1
    assert out[0].claim == "line one line two line three"
    assert out[0].confidence == "MED"


def test_multiline_finding_among_other_findings():
    text = (
        "[FINDING] single line claim.\n"
        "[EVIDENCE: a]\n[CONFIDENCE: HIGH]\n\n"
        "[FINDING] a claim that wraps\n"
        "onto a second line.\n"
        "[EVIDENCE: b]\n[CONFIDENCE: LOW]\n"
    )
    out = parse_findings(text)
    assert len(out) == 2
    assert out[0].claim == "single line claim."
    assert out[1].claim == "a claim that wraps onto a second line."
    assert out[1].confidence == "LOW"


def test_multiline_claim_with_blank_line_before_evidence_still_parses():
    # a blank line inside the block (before the evidence) is tolerated, not joined
    text = (
        "[FINDING] claim first line\n"
        "claim second line\n"
        "\n"
        "[EVIDENCE: src]\n"
        "[CONFIDENCE: HIGH]\n"
    )
    out = parse_findings(text)
    assert len(out) == 1
    assert out[0].claim == "claim first line claim second line"


def test_multiline_finding_hitting_confidence_before_evidence_loud_fails():
    # if the lookahead reaches a [CONFIDENCE] (or another [FINDING]) before any
    # [EVIDENCE], the block is genuinely malformed — must still loud-fail. This
    # keeps test_finding_followed_by_prose_instead_of_evidence_loud_fails valid:
    # wrapped prose that never reaches evidence is an error, not a claim.
    text = (
        "[FINDING] claim with wrapped prose\n"
        "that never gets an evidence tag\n"
        "[CONFIDENCE: HIGH]\n"
    )
    with pytest.raises(ReportParseError):
        parse_findings(text)


def test_multiline_finding_running_off_end_loud_fails():
    text = (
        "[FINDING] claim that wraps\n"
        "and then the report just ends\n"
    )
    with pytest.raises(ReportParseError):
        parse_findings(text)


def test_multiline_finding_hitting_next_finding_before_evidence_loud_fails():
    text = (
        "[FINDING] first claim wraps\n"
        "and never gets evidence\n"
        "[FINDING] second claim.\n"
        "[EVIDENCE: b]\n[CONFIDENCE: LOW]\n"
    )
    with pytest.raises(ReportParseError):
        parse_findings(text)
