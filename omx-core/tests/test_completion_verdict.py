"""Tests for omx_core.completion.evaluate_completion (design doc §4) — the
run-completion verdict engine. Fixture trees under tmp_path; no network, no ssh."""
import os

import pytest
from omx_core.completion import evaluate_completion
from omx_core.omx_paths import OmxPaths
from omx_core.profile import bootstrap_profile, default_metrics

CONTRACT = {
    "runs": "runs/*",
    "finished": "checkpoints/*.pt",
    "exclude": ["runs/smoke-*"],
    "required": ["eval/*.json", "plots/*.png"],
    "how": "python analysis/eval.py static --run {run}",
}


def _setup(tmp_path, run_completion=CONTRACT, output_root="experiments"):
    paths = OmxPaths(root=tmp_path)
    metrics = default_metrics()
    metrics["output_root"] = output_root
    if run_completion is not None:
        metrics["run_completion"] = run_completion
    bootstrap_profile(paths, profile_name="isaaclab", metrics=metrics)
    return paths


def _finish(run_dir):
    (run_dir / "checkpoints").mkdir(parents=True)
    (run_dir / "checkpoints" / "final.pt").write_text("x")


def _satisfy_required(run_dir):
    (run_dir / "eval").mkdir(exist_ok=True)
    (run_dir / "eval" / "summary.json").write_text("{}")
    (run_dir / "plots").mkdir(exist_ok=True)
    (run_dir / "plots" / "curve.png").write_text("x")


def test_no_contract_returns_no_contract_state(tmp_path):
    _setup(tmp_path, run_completion=None)
    result = evaluate_completion(tmp_path)
    assert result == {
        "state": "no-contract", "runs": [], "missing": [], "output_root": None, "how": None,
    }


def test_finished_run_without_artifacts_is_incomplete(tmp_path):
    _setup(tmp_path)
    run_dir = tmp_path / "experiments" / "runs" / "alpha"
    _finish(run_dir)
    result = evaluate_completion(tmp_path)
    assert result["state"] == "incomplete"
    assert result["missing"] == [{
        "run": "runs/alpha",
        "missing": ["eval/*.json", "plots/*.png"],
        "how": "python analysis/eval.py static --run runs/alpha",
    }]
    assert result["how"] == "python analysis/eval.py static --run {run}"  # top-level how unsubstituted


def test_same_tree_with_artifacts_created_is_checked(tmp_path):
    _setup(tmp_path)
    run_dir = tmp_path / "experiments" / "runs" / "alpha"
    _finish(run_dir)
    _satisfy_required(run_dir)
    result = evaluate_completion(tmp_path)
    assert result["state"] == "checked"
    assert result["missing"] == []
    assert result["runs"] == ["runs/alpha"]


def test_exclude_keeps_smoke_run_out_of_subject_set(tmp_path):
    _setup(tmp_path)
    run_dir = tmp_path / "experiments" / "runs" / "smoke-1"
    _finish(run_dir)  # finished but excluded -- must not demand artifacts
    result = evaluate_completion(tmp_path)
    assert result["state"] == "checked"
    assert result["runs"] == []
    assert result["missing"] == []


def test_unfinished_run_is_not_a_subject(tmp_path):
    _setup(tmp_path)
    run_dir = tmp_path / "experiments" / "runs" / "alpha"
    run_dir.mkdir(parents=True)  # no checkpoints/ at all
    result = evaluate_completion(tmp_path)
    assert result["state"] == "checked"
    assert result["runs"] == []
    assert result["missing"] == []


def test_missing_output_root_is_unreadable_not_checked(tmp_path):
    _setup(tmp_path)
    # "experiments" is never created
    result = evaluate_completion(tmp_path)
    assert result["state"] == "unreadable"
    assert result["output_root"] == str(tmp_path / "experiments")


def test_readable_output_root_zero_run_dirs_is_checked(tmp_path):
    _setup(tmp_path)
    (tmp_path / "experiments").mkdir()
    result = evaluate_completion(tmp_path)
    assert result["state"] == "checked"
    assert result["runs"] == []
    assert result["missing"] == []


def test_output_root_resolved_relative_to_omx_root(tmp_path):
    paths = _setup(tmp_path, output_root="nested/experiments")
    run_dir = tmp_path / "nested" / "experiments" / "runs" / "alpha"
    _finish(run_dir)
    _satisfy_required(run_dir)
    result = evaluate_completion(paths)
    assert result["state"] == "checked"
    assert result["output_root"] == str(tmp_path / "nested" / "experiments")


def test_required_glob_matching_a_directory_does_not_satisfy_it(tmp_path):
    _setup(tmp_path)
    run_dir = tmp_path / "experiments" / "runs" / "alpha"
    _finish(run_dir)
    (run_dir / "eval").mkdir()
    (run_dir / "eval" / "summary.json").mkdir()  # placeholder DIR, not a file
    (run_dir / "plots").mkdir()
    (run_dir / "plots" / "curve.png").write_text("x")
    result = evaluate_completion(tmp_path)
    assert result["state"] == "incomplete"
    assert result["missing"] == [{
        "run": "runs/alpha",
        "missing": ["eval/*.json"],
        "how": "python analysis/eval.py static --run runs/alpha",
    }]


def test_finished_glob_matching_a_directory_does_not_count_as_finished(tmp_path):
    _setup(tmp_path)
    run_dir = tmp_path / "experiments" / "runs" / "alpha"
    (run_dir / "checkpoints").mkdir(parents=True)
    (run_dir / "checkpoints" / "final.pt").mkdir()  # placeholder DIR, not a file
    result = evaluate_completion(tmp_path)
    assert result["state"] == "checked"  # not finished -> not a subject -> zero-run honest pass
    assert result["runs"] == []


def test_run_glob_matching_a_file_is_silently_skipped(tmp_path):
    _setup(tmp_path)
    (tmp_path / "experiments" / "runs").mkdir(parents=True)
    (tmp_path / "experiments" / "runs" / "stray_file").write_text("not a run dir")
    result = evaluate_completion(tmp_path)
    assert result["state"] == "checked"
    assert result["runs"] == []


@pytest.mark.skipif(
    os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="requires POSIX permission enforcement as a non-root user",
)
def test_permission_denied_on_output_root_is_unreadable(tmp_path):
    _setup(tmp_path)
    out = tmp_path / "experiments"
    out.mkdir()
    (out / "runs").mkdir()
    os.chmod(out, 0o000)
    try:
        result = evaluate_completion(tmp_path)
    finally:
        os.chmod(out, 0o755)
    assert result["state"] == "unreadable"
