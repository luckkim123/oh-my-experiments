"""Tests for omx_core.completion.evaluate_completion (design doc §4) — the
run-completion verdict engine. Fixture trees under tmp_path; no network, no ssh."""
import os

import pytest
import yaml
from omx_core.completion import evaluate_completion
from omx_core.omx_paths import OmxPaths
from omx_core.profile import bootstrap_profile, default_metrics

_SKIP_UNLESS_POSIX_NONROOT = pytest.mark.skipif(
    os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="requires POSIX permission enforcement as a non-root user",
)

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
        "state": "no-contract", "runs": [], "missing": [], "subject_count": None,
        "output_root": None, "how": None, "reason": None,
        # Ruling 39 (task 14): the profile parsed fine, `run_completion` is simply
        # absent -- the ONE no-contract cause hooks/handlers.py:completion_notice
        # needs distinguished from the other (see the no-profile/unparseable
        # tests below, which stay `no_contract_reason: None`).
        "no_contract_reason": "no_run_completion_key",
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
    # excluded runs never survive `exclude`, so they don't count as subjects either --
    # same 0 as the genuinely-empty-tree case (test_readable_output_root_zero_run_dirs_is_checked),
    # which is correct: both are "nothing eligible", not "something eligible but unfinished".
    assert result["subject_count"] == 0


def test_unfinished_run_is_not_a_subject(tmp_path):
    _setup(tmp_path)
    run_dir = tmp_path / "experiments" / "runs" / "alpha"
    run_dir.mkdir(parents=True)  # no checkpoints/ at all
    result = evaluate_completion(tmp_path)
    assert result["state"] == "checked"
    assert result["runs"] == []
    assert result["missing"] == []
    # one run dir matched `runs` and survived `exclude` but wasn't finished -- distinct
    # from a genuinely empty tree (subject_count 0): this is the case a typo'd `finished`
    # glob would produce, and subject_count > 0 with runs == [] is how a reader tells them apart.
    assert result["subject_count"] == 1


def test_missing_output_root_is_checked_not_unreadable(tmp_path):
    """Ruling 29 (task-5 fix-round-2), reversing this test's original
    assertion: a NEVER-CREATED output_root is a definite answer (nothing
    there, therefore no finished runs) -- the exact shape of every project
    between declaring a contract and finishing its first run. It is NOT the
    same fact as "I cannot tell" (a permission-denied or genuinely broken
    tree, still `unreadable` -- see test_output_root_broken_symlink_is_unreadable
    and test_output_root_is_a_file_not_a_directory_is_unreadable below,
    unchanged). Same shape as test_readable_output_root_zero_run_dirs_is_checked
    (a pass), distinguished only by a non-None `reason` a human can see.

    NARROWED by Ruling 36 (task-10 fix-round-1) to the case this fixture has
    always actually been: `_setup`'s default `output_root="experiments"` is
    RELATIVE. Ruling 36 split what this test used to claim for "any missing
    output_root" -- see test_absolute_missing_output_root_is_unreadable_not_checked
    below for the ABSOLUTE case, which now denies instead."""
    _setup(tmp_path)
    # "experiments" is never created
    result = evaluate_completion(tmp_path)
    assert result["state"] == "checked"
    assert result["runs"] == []
    assert result["missing"] == []
    assert result["subject_count"] == 0
    assert result["output_root"] == str(tmp_path / "experiments")
    assert "does not exist" in result["reason"]


def test_absolute_missing_output_root_is_unreadable_not_checked(tmp_path):
    """Ruling 36 (task-10 fix-round-1): the case Ruling 29 above did NOT
    cover and the design's own ssh crossing (design §5) depends on -- a
    project whose output tree sits behind ssh declares `output_root` as the
    ABSOLUTE remote path (a container-shaped example: "/workspace/albc/
    experiments", not a generic /tmp path), and if THIS machine cannot see
    it, that is "I cannot tell", not "nothing to grade yet". Before this
    fix, an absolute-and-missing output_root read identically to a
    relative-and-missing one (`checked`) -- the exact defect this whole
    round exists to remove, reproduced live by the team lead against this
    branch's own Ruling-29 code and confirmed here."""
    output_root = "/workspace/albc/experiments"  # absolute; deliberately does not exist on this machine
    _setup(tmp_path, output_root=output_root)
    result = evaluate_completion(tmp_path)
    assert result["state"] == "unreadable"
    assert result["runs"] == []
    assert result["missing"] == []
    assert result["subject_count"] is None
    assert result["output_root"] == output_root
    assert "absolute" in result["reason"]
    assert "not present on this machine" in result["reason"]


def test_readable_output_root_zero_run_dirs_is_checked(tmp_path):
    _setup(tmp_path)
    (tmp_path / "experiments").mkdir()
    result = evaluate_completion(tmp_path)
    assert result["state"] == "checked"
    assert result["runs"] == []
    assert result["missing"] == []
    assert result["subject_count"] == 0  # the honest zero: genuinely nothing matched `runs`


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


@_SKIP_UNLESS_POSIX_NONROOT
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


# --- Finding 1: an unreadable subtree at ANY depth below output_root must read as
# `unreadable`, never as "no runs, pass" -- Path.glob() silently swallows OSError at
# every level of its own walk, so this must not be checked via glob() alone. One test
# per row of the reviewed table.

@_SKIP_UNLESS_POSIX_NONROOT
def test_unreadable_runs_directory_is_unreadable_not_checked(tmp_path):
    _setup(tmp_path)
    runs_dir = tmp_path / "experiments" / "runs"
    run_dir = runs_dir / "alpha"
    _finish(run_dir)
    _satisfy_required(run_dir)
    os.chmod(runs_dir, 0o000)
    try:
        result = evaluate_completion(tmp_path)
    finally:
        os.chmod(runs_dir, 0o755)
    assert result["state"] == "unreadable"


@_SKIP_UNLESS_POSIX_NONROOT
def test_unreadable_run_dir_itself_is_unreadable_not_checked(tmp_path):
    _setup(tmp_path)
    run_dir = tmp_path / "experiments" / "runs" / "alpha"
    _finish(run_dir)
    _satisfy_required(run_dir)
    os.chmod(run_dir, 0o000)
    try:
        result = evaluate_completion(tmp_path)
    finally:
        os.chmod(run_dir, 0o755)
    assert result["state"] == "unreadable"


@_SKIP_UNLESS_POSIX_NONROOT
def test_unreadable_checkpoints_subdir_is_unreadable_not_checked(tmp_path):
    _setup(tmp_path)
    run_dir = tmp_path / "experiments" / "runs" / "alpha"
    _finish(run_dir)
    _satisfy_required(run_dir)
    checkpoints_dir = run_dir / "checkpoints"
    os.chmod(checkpoints_dir, 0o000)
    try:
        result = evaluate_completion(tmp_path)
    finally:
        os.chmod(checkpoints_dir, 0o755)
    assert result["state"] == "unreadable"
    # reason names the OFFENDING path -- the checkpoints/ subdir, not just output_root
    assert str(checkpoints_dir) in result["reason"]


def test_output_root_broken_symlink_is_unreadable(tmp_path):
    _setup(tmp_path)
    (tmp_path / "experiments").symlink_to(tmp_path / "does_not_exist_target")
    result = evaluate_completion(tmp_path)
    assert result["state"] == "unreadable"


# --- Finding 5(a): output_root exists but is a FILE, not a directory.

def test_output_root_is_a_file_not_a_directory_is_unreadable(tmp_path):
    _setup(tmp_path)
    (tmp_path / "experiments").write_text("not a directory")
    result = evaluate_completion(tmp_path)
    assert result["state"] == "unreadable"


# --- Finding 7 (+ round-1 addendum item A): a profile that opted into the gate
# (declared run_completion) and then broke itself -- output_root removed, OR the
# run_completion block itself now malformed -- must resolve to `unreadable`, not
# raise. A raise hits the hook's fail-open (D9) and becomes a silent ALLOW, which is
# the exact hole this round exists to close. `reason` (item B) names which of the
# two causes fired.

def test_malformed_output_root_is_unreadable_not_raise(tmp_path):
    paths = _setup(tmp_path)
    metrics_path = paths.profile_file("metrics.yaml")
    data = yaml.safe_load(metrics_path.read_text())
    del data["output_root"]  # simulate a profile broken after the contract was declared
    metrics_path.write_text(yaml.safe_dump(data, sort_keys=True))
    result = evaluate_completion(tmp_path)  # must not raise
    assert result["state"] == "unreadable"
    assert "output_root" in result["reason"]


def test_malformed_run_completion_block_is_unreadable_not_raise(tmp_path):
    # validate_run_completion (task 1) still raises OmxError for this shape when
    # called directly -- evaluate_completion is the one caller that must downgrade
    # it, since a raise here meets the hook's fail-open and becomes a silent ALLOW.
    bad_contract = dict(CONTRACT)
    bad_contract["required"] = [42]  # not a list of strings -- the reviewer's own repro
    _setup(tmp_path, run_completion=bad_contract)
    result = evaluate_completion(tmp_path)  # must not raise
    assert result["state"] == "unreadable"
    assert "required" in result["reason"]


# --- Finding 8: the run_completion KEY is the opt-in signal, and it is literal. A
# missing profile, an unparseable metrics.yaml, or a profile with no run_completion
# key at all are three ways of saying "never opted in" -- no-contract, allowed,
# silently. Collapsing these into the same `unreadable` a malformed BLOCK produces
# (finding 7) would deny every unrelated project on the machine (success criterion 3
# inverted). One test per row of the reviewed table, plus the explicit "unrelated
# directory" case the finding called out by name.

def test_omx_dir_present_but_no_profile_is_no_contract(tmp_path):
    # .omx/ exists (partial setup) but exp-init never ran -- no profile file at all.
    (tmp_path / ".omx").mkdir()
    result = evaluate_completion(tmp_path)
    assert result["state"] == "no-contract"
    # Ruling 39 (task 14): this cause is NOT the "profile parsed fine, key
    # absent" one -- no_contract_reason stays None, same as before this field
    # existed. completion_notice relies on exactly this to stay silent here.
    assert result["no_contract_reason"] is None


def test_no_omx_store_at_all_is_no_contract(tmp_path):
    # tmp_path is used completely bare here -- an unrelated directory with no omx
    # store whatsoever, e.g. any other repository on the machine. This is the
    # blast-radius case: before this fix, every such directory read as unreadable.
    result = evaluate_completion(tmp_path)
    assert result["state"] == "no-contract"
    assert result["no_contract_reason"] is None


def test_metrics_yaml_parses_as_non_mapping_is_no_contract(tmp_path):
    paths = OmxPaths(root=tmp_path)
    metrics_path = paths.profile_file("metrics.yaml")
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text("- not\n- a\n- mapping\n")
    result = evaluate_completion(tmp_path)
    assert result["state"] == "no-contract"
    assert result["no_contract_reason"] is None
