from omx_core.report import Finding, parse_findings


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
