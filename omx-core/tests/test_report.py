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
