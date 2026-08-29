"""Quality scoring, after B4 moved the page store to hq.

Two tests that used to live here are gone with the schema they checked:
`quality_fields_roundtrip` and `old_pages_serialize_without_quality_keys`
asserted on `WikiPage` serialization, and there is no WikiPage any more. So is
`lint_surfaces_low_quality` -- `hq lint` has no quality-floor concept, which is
a real capability loss recorded in the CHANGELOG rather than a test to rewrite.

What survives is the scorer itself, which is still omx's, and the `wiki add`
gate that forces confidence low below the floor -- now checked at the seam where
it is observable: the `--confidence` argv omx hands to `hq post`.
"""
import json

import pytest
from conftest import hq_stub
from omx_core.cli import main
from omx_core.wiki import hq_backend
from omx_core.wiki.quality import QUALITY_FLOOR, score_page

RICH = ("Constraint cost dropped 0.5 -> 0.2 at iter 800; verified via "
        "`omx reduce tb-final` against Loss/cost_value. See analysis/eval.py:12. "
        "[EVIDENCE: summary.json] Reproduced on both none and hard DR levels.")


@pytest.fixture
def hq_spy(monkeypatch):
    """Record every argv omx hands to hq, answering as an empty store."""
    import subprocess as _sp

    calls = []
    monkeypatch.undo()

    def _run(cmd, **kw):
        calls.append(cmd)
        # Dispatch on the VERB, not on `--subject`: `hq post` carries
        # `--subject` too, so keying off the flag answered a write with a
        # query's payload and the caller died on a missing `id`.
        verb = cmd[cmd.index("--json") + 1] if "--json" in cmd else ""
        if verb == "query":
            payload = {"canonical": None, "shadowed": [], "ambiguous": False, "posts": []}
        else:
            payload = {"id": "finding/001"}
        return _sp.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(hq_backend, "subprocess", hq_stub(_run))
    return calls


def test_rich_page_scores_high():
    score, reasons = score_page(RICH, ["constraint", "trpo"],
                                title="Constraint cost drop root cause")
    assert score == 100 and reasons == []


def test_penalties_accumulate():
    score, reasons = score_page("short note", ["misc"], title="notes")
    assert score == 100 - 30 - 20 - 20 - 10 - 10
    assert set(reasons) == {"body-under-120-chars", "no-numeric-token",
                            "no-source-marker", "generic-only-tags", "weak-title"}


def test_score_clamped_at_zero():
    score, _ = score_page("", [], title="")
    assert score >= 0


def test_wiki_add_forces_low_below_floor(tmp_path, capsys, hq_spy):
    rc = main(["wiki", "add", "--root", str(tmp_path), "--title", "notes",
               "--category", "reference", "--confidence", "high",
               "--content", "short note", "--tags", "misc"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["quality_forced_low"] is True and out["quality_score"] < QUALITY_FLOOR
    # The forcing has to reach the store, not just the report: check the argv.
    post = [c for c in hq_spy if "post" in c][0]
    assert post[post.index("--confidence") + 1] == "low"


def test_wiki_add_keeps_confidence_above_floor(tmp_path, capsys, hq_spy):
    rc = main(["wiki", "add", "--root", str(tmp_path),
               "--title", "Constraint cost drop root cause",
               "--category", "decision", "--confidence", "high",
               "--content", RICH, "--tags", "constraint,trpo"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["quality_forced_low"] is False
    post = [c for c in hq_spy if "post" in c][0]
    assert post[post.index("--confidence") + 1] == "high"
