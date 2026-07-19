import json

from omx_core.cli import main
from omx_core.wiki.quality import QUALITY_FLOOR, score_page
from omx_core.wiki.storage import parse_page, serialize_page
from omx_core.wiki.types import WikiPage

RICH = ("Constraint cost dropped 0.5 -> 0.2 at iter 800; verified via "
        "`omx reduce tb-final` against Loss/cost_value. See analysis/eval.py:12. "
        "[EVIDENCE: summary.json] Reproduced on both none and hard DR levels.")


def test_rich_page_scores_high():
    score, reasons = score_page(RICH, ["constraint", "trpo"], title="Constraint cost drop root cause")
    assert score == 100 and reasons == []


def test_penalties_accumulate():
    score, reasons = score_page("short note", ["misc"], title="notes")
    assert score == 100 - 30 - 20 - 20 - 10 - 10
    assert set(reasons) == {"body-under-120-chars", "no-numeric-token",
                            "no-source-marker", "generic-only-tags", "weak-title"}


def test_score_clamped_at_zero():
    score, _ = score_page("", [], title="")
    assert score >= 0


def test_quality_fields_roundtrip():
    page = WikiPage(slug="p.md", title="t", quality_score=40,
                    quality_reasons=["no-numeric-token"], content="body")
    text = serialize_page(page)
    back = parse_page("p.md", text)
    assert back.quality_score == 40 and back.quality_reasons == ["no-numeric-token"]


def test_old_pages_serialize_without_quality_keys():
    page = WikiPage(slug="p.md", title="t", content="body")
    assert "qualityScore" not in serialize_page(page)


def test_wiki_add_forces_low_below_floor(tmp_path, capsys):
    rc = main(["wiki", "add", "--root", str(tmp_path), "--title", "notes",
               "--category", "reference", "--confidence", "high",
               "--content", "short note", "--tags", "misc"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["quality_forced_low"] is True and out["quality_score"] < QUALITY_FLOOR
    from omx_core.omx_paths import OmxPaths
    from omx_core.wiki import storage
    page = storage.read_page(OmxPaths(root=tmp_path), out["slug"])
    assert page.confidence == "low" and page.quality_score == out["quality_score"]


def test_wiki_add_keeps_confidence_above_floor(tmp_path, capsys):
    rc = main(["wiki", "add", "--root", str(tmp_path),
               "--title", "Constraint cost drop root cause",
               "--category", "decision", "--confidence", "high",
               "--content", RICH, "--tags", "constraint,trpo"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["quality_forced_low"] is False


def test_lint_surfaces_low_quality(tmp_path, capsys):
    main(["wiki", "add", "--root", str(tmp_path), "--title", "notes",
          "--category", "reference", "--confidence", "medium",
          "--content", "short note", "--tags", "misc"])
    capsys.readouterr()
    rc = main(["wiki", "lint", "--root", str(tmp_path)])
    assert rc == 0
    res = json.loads(capsys.readouterr().out)
    assert "low-quality" in res["stats"]["by_type"]
