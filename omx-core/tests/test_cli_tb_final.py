"""CLI tests for `omx reduce tb-final` — ingest a TB source, print named
final-window means for the requested tags as JSON. Models on test_cli's
reduce-summarize + test_cli_plot's TB-fixture usage."""
import json

import pytest

from omx_core.cli import main


def test_tb_final_single_tag(fixtures_dir, capsys):
    ev = fixtures_dir / "tb" / "events.out.tfevents.synthetic"
    # Reward/total = [-0.5,-0.4,-0.3,-0.2,-0.1]; last 2 mean = -0.15
    rc = main(["reduce", "tb-final", "--path", str(ev), "--format", "tensorboard",
               "--tag", "Reward/total", "--window", "2"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["window"] == 2
    assert out["final"]["Reward/total"] == pytest.approx(-0.15)


def test_tb_final_multiple_tags(fixtures_dir, capsys):
    ev = fixtures_dir / "tb" / "events.out.tfevents.synthetic"
    rc = main(["reduce", "tb-final", "--path", str(ev), "--format", "tensorboard",
               "--tag", "Reward/total", "--tag", "Track/att/roll_err_deg",
               "--window", "2"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["final"]["Reward/total"] == pytest.approx(-0.15)
    assert out["final"]["Track/att/roll_err_deg"] == pytest.approx(13.0)


def test_tb_final_default_window_averages_all_when_short(fixtures_dir, capsys):
    ev = fixtures_dir / "tb" / "events.out.tfevents.synthetic"
    # only 5 samples, default window 200 -> mean of all = -0.3
    rc = main(["reduce", "tb-final", "--path", str(ev), "--format", "tensorboard",
               "--tag", "Reward/total"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["window"] == 200
    assert out["final"]["Reward/total"] == pytest.approx(-0.3)


def test_tb_final_absent_tag_loud_fails(fixtures_dir, capsys):
    ev = fixtures_dir / "tb" / "events.out.tfevents.synthetic"
    # an absent tag must NOT yield 0 — it is a loud failure (the incident: trust
    # an empty/zero engine cell as "no data"). The error lists available tags.
    rc = main(["reduce", "tb-final", "--path", str(ev), "--format", "tensorboard",
               "--tag", "Reward/nope"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "Reward/nope" in err
    assert "Reward/total" in err  # available tags surfaced to the caller
