"""Task 4 -- CLI verbs for the run-completion gate (design doc §4/§5/§6).

close-check computes+reports the verdict (0 no-contract/checked, 1 incomplete,
2 unreadable). close-ack ingests a `close-check --json` payload produced
elsewhere and stores it as a receipt (source: remote), refusing anything that
isn't a fresh `checked` state. close-defer records a human's dated, reasoned
decision to close anyway.

Fixture trees under tmp_path, same shape as test_completion_verdict.py.
`cli.main([...])` returns the rc directly (tests/test_ledger_verbs.py idiom).
"""
import json
from datetime import timedelta

from omx_core.clock import now_iso, parse_iso_utc
from omx_core.completion import read_defer, read_receipt, write_receipt
from omx_core.omx_paths import OmxPaths, has_anchor, runtime_dir
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


def _receipt_file(paths):
    return (runtime_dir(paths.root) if has_anchor(paths.root) else paths.omx_dir) / "completion-receipt.json"


def _defer_file(paths):
    return (runtime_dir(paths.root) if has_anchor(paths.root) else paths.omx_dir) / "completion-defer.json"


# --- close-check: the four verdict states -----------------------------------

def test_close_check_no_contract_exits_0(tmp_path, capsys):
    from omx_core import cli
    _setup(tmp_path, run_completion=None)
    rc = cli.main(["close-check", "--root", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["state"] == "no-contract"


def test_close_check_checked_zero_runs_exits_0(tmp_path, capsys):
    from omx_core import cli
    _setup(tmp_path)
    (tmp_path / "experiments").mkdir()
    rc = cli.main(["close-check", "--root", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["state"] == "checked"
    assert out["subject_count"] == 0


def test_close_check_incomplete_exits_1(tmp_path, capsys):
    from omx_core import cli
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    rc = cli.main(["close-check", "--root", str(tmp_path), "--json"])
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert rc == 1
    assert out["state"] == "incomplete"
    assert out["missing"][0]["run"] == "runs/alpha"
    # fix-round-2 negative control: no defer file at all is the common,
    # unremarkable case -- must not trigger _warn_if_defer_present_but_unreadable.
    assert captured.err == ""


def test_close_check_unreadable_exits_2(tmp_path, capsys):
    """Ruling 29 (task-5 fix-round-2): a never-created output_root is no
    longer unreadable (it's `checked` -- see test_close_check_missing_output_root_exits_0
    below), so this genuinely-unreadable fixture is a FILE where a directory
    was declared -- "output_root is not a directory" is unchanged."""
    from omx_core import cli
    _setup(tmp_path, output_root="not-a-dir")
    (tmp_path / "not-a-dir").write_text("nope")
    rc = cli.main(["close-check", "--root", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert out["state"] == "unreadable"
    assert out["reason"]  # requirement 2: reason surfaces, not paraphrased away


def test_close_check_missing_output_root_exits_0(tmp_path, capsys):
    """Ruling 29 (task-5 fix-round-2): the never-created case is now a PASS
    (there is nothing there yet, a definite answer), with a reason a human
    can still see -- distinct from the genuinely-unreadable FILE case above.

    NARROWED by Ruling 36 (task-10 fix-round-1): "never-created" here is a
    RELATIVE output_root, which stays exactly this -- a pass. See
    test_close_check_absolute_missing_output_root_exits_2 below for the
    ABSOLUTE case, which denies."""
    from omx_core import cli
    _setup(tmp_path, output_root="never-created")
    rc = cli.main(["close-check", "--root", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["state"] == "checked"
    assert out["subject_count"] == 0
    assert "does not exist" in out["reason"]


def test_close_check_absolute_missing_output_root_exits_2(tmp_path, capsys):
    """Ruling 36 (task-10 fix-round-1): the case the sibling test above does
    NOT cover -- an ABSOLUTE, container-shaped output_root ("/workspace/albc/
    experiments", the exact repro the team lead used) that does not exist on
    THIS machine. This is design §5's ssh-crossing shape, and before this
    fix it silently passed at rc 0 just like the relative case -- the gate
    was off for exactly the project this round was built for. Verified
    through the real CLI entry point (cli.main), not evaluate_completion
    directly, since rc is what an operator/hook actually sees."""
    from omx_core import cli
    _setup(tmp_path, output_root="/workspace/albc/experiments")
    rc = cli.main(["close-check", "--root", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert out["state"] == "unreadable"
    assert "absolute" in out["reason"]
    assert "not present on this machine" in out["reason"]


def test_close_check_human_output_distinguishes_relative_from_absolute_missing(tmp_path, capsys):
    """Ruling 36 (task-10 fix-round-1), same discipline as Ruling 29's
    round-3 fix (test_close_check_checked_human_output_distinguishes_missing_from_empty
    below): the human-readable line -- what an operator actually reads, not
    --json -- must differ between the two missing-output_root shapes, not
    just carry the distinction in the JSON payload."""
    from omx_core import cli
    relative_root = tmp_path / "rel-case"
    relative_root.mkdir()
    _setup(relative_root, output_root="never-created")
    cli.main(["close-check", "--root", str(relative_root)])
    relative_out = capsys.readouterr().out

    absolute_root = tmp_path / "abs-case"
    absolute_root.mkdir()
    _setup(absolute_root, output_root="/workspace/albc/experiments")
    cli.main(["close-check", "--root", str(absolute_root)])
    absolute_out = capsys.readouterr().out

    assert relative_out != absolute_out
    assert relative_out.startswith("PASS")
    assert absolute_out.startswith("FAIL")


# --- close-check human output ------------------------------------------------

def test_close_check_human_output_shows_run_missing_how(tmp_path, capsys):
    from omx_core import cli
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    rc = cli.main(["close-check", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "runs/alpha" in out
    assert "eval/*.json" in out
    assert "python analysis/eval.py static --run runs/alpha" in out


def test_close_check_unreadable_human_output_names_reason(tmp_path, capsys):
    """Ruling 29 (task-5 fix-round-2): same fixture swap as
    test_close_check_unreadable_exits_2 -- never-created is now a pass."""
    from omx_core import cli
    _setup(tmp_path, output_root="not-a-dir")
    (tmp_path / "not-a-dir").write_text("nope")
    rc = cli.main(["close-check", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 2
    assert "not-a-dir" in out


def test_close_check_checked_human_output_distinguishes_missing_from_empty(tmp_path, capsys):
    """Ruling 29 (task-5 fix-round-3): the JSON payload already carried a
    distinct `reason` for a missing output_root, but `_print_close_check_human`
    was dropping it, so the human-readable line -- the one an operator
    actually reads, not --json -- was byte-identical for "never ran" and
    "genuinely empty tree". Assert the two outputs literally DIFFER, not
    just that one contains "does not exist": that weaker assertion would
    still pass if the empty-tree case ever grew the same text by accident."""
    from omx_core import cli
    _setup(tmp_path)
    rc_missing = cli.main(["close-check", "--root", str(tmp_path)])
    out_missing = capsys.readouterr().out

    (tmp_path / "experiments").mkdir()  # now make the SAME path exist, empty
    rc_empty = cli.main(["close-check", "--root", str(tmp_path)])
    out_empty = capsys.readouterr().out

    assert rc_missing == 0 and rc_empty == 0
    assert out_missing != out_empty
    assert "does not exist" in out_missing
    assert "does not exist" not in out_empty
    # the first line (the PASS summary) is unchanged in both -- only a
    # SECOND line is added for the missing case, per the controller's
    # instruction to keep the no-reason line untouched.
    assert out_missing.splitlines()[0] == out_empty.splitlines()[0]


def test_close_check_unreadable_from_malformed_contract_block_has_no_none_prefix(tmp_path, capsys):
    """A malformed run_completion block fails before output_root is ever read,
    so evaluate_completion returns output_root=None -- the human line must not
    print a literal "None: " prefix in front of the reason (adversarial finding)."""
    from omx_core import cli
    _setup(tmp_path, run_completion={"runs": 123})  # missing required keys
    rc = cli.main(["close-check", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 2
    assert "None:" not in out
    assert "run_completion" in out


# --- requirement 1: subject_count distinguishes the honest zero -------------

def test_close_check_checked_with_unfinished_candidate_has_nonzero_subject_count(tmp_path, capsys):
    from omx_core import cli
    _setup(tmp_path)
    (tmp_path / "experiments" / "runs" / "unfinished").mkdir(parents=True)
    rc = cli.main(["close-check", "--root", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["state"] == "checked"
    assert out["subject_count"] == 1  # "1 candidate, none finished" != "0 candidates"
    assert out["runs"] == []


def test_close_check_human_output_names_subject_count(tmp_path, capsys):
    """fix-round-1 reviewer finding 2: the original `assert "1" in out` did not
    discriminate -- pytest's own tmp_path (e.g. .../pytest-201/...) coincidentally
    contains a '1' regardless of whether the code prints the count at all (confirmed
    by reverting the print to a literal 'REDACTED' and watching this still pass).
    Assert the exact composed clause instead, which no incidental digit can satisfy."""
    from omx_core import cli
    _setup(tmp_path)
    (tmp_path / "experiments" / "runs" / "unfinished").mkdir(parents=True)
    cli.main(["close-check", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert "out of 1 candidate run directory" in out


# --- close-check --record ----------------------------------------------------

def test_close_check_record_writes_local_receipt(tmp_path, capsys):
    from omx_core import cli
    run_dir = tmp_path / "experiments" / "runs" / "alpha"
    _setup(tmp_path)
    _finish(run_dir)
    _satisfy_required(run_dir)
    rc = cli.main(["close-check", "--root", str(tmp_path), "--record", "--json"])
    capsys.readouterr()
    assert rc == 0
    receipt = read_receipt(OmxPaths(root=tmp_path))
    assert receipt["state"] == "checked"
    assert receipt["source"] == "local"
    assert receipt["root"] == str(tmp_path)


def test_close_check_record_still_writes_receipt_for_a_failing_verdict(tmp_path, capsys):
    """write_receipt accepts any state (task 3); --record is an unconditional
    audit trail, not gated on the check passing."""
    from omx_core import cli
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    rc = cli.main(["close-check", "--root", str(tmp_path), "--record", "--json"])
    capsys.readouterr()
    assert rc == 1
    receipt = read_receipt(OmxPaths(root=tmp_path))
    assert receipt["state"] == "incomplete"


# --- close-check rescued by an active defer ----------------------------------

def test_close_check_rescued_by_active_defer(tmp_path, capsys):
    from omx_core import cli
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")  # incomplete on its own
    cli.main(["close-defer", "--root", str(tmp_path), "--reason", "waiting on hardware"])
    capsys.readouterr()
    rc = cli.main(["close-check", "--root", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["state"] == "incomplete"  # underlying truth is preserved, not overwritten
    assert out["satisfied_by"]["via"] == "defer"
    assert out["satisfied_by"]["reason"] == "waiting on hardware"


def test_close_check_clean_pass_human_text_names_neither_defer_nor_receipt(tmp_path, capsys):
    from omx_core import cli
    run_dir = tmp_path / "experiments" / "runs" / "alpha"
    _setup(tmp_path)
    _finish(run_dir)
    _satisfy_required(run_dir)
    rc = cli.main(["close-check", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "defer" not in out.lower()
    assert "receipt" not in out.lower()


def test_close_check_deferred_pass_human_text_names_the_defer(tmp_path, capsys):
    from omx_core import cli
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")  # incomplete on its own
    cli.main(["close-defer", "--root", str(tmp_path), "--reason", "waiting on hardware"])
    capsys.readouterr()
    rc = cli.main(["close-check", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "defer" in out.lower()
    assert "waiting on hardware" in out


def test_close_check_defer_missing_reason_does_not_crash_and_does_not_satisfy(tmp_path, capsys):
    """fix-round-1 controller finding A: a defer file that is timestamp-fresh
    (active_defer -> True) but hand-edited to drop 'reason' entirely must not
    raise KeyError, and -- ruling -- must not be treated as an active escape
    either (a defer without a readable reason is not a recorded one). The
    check falls through to fail on its own merits (rc 1, incomplete)."""
    from omx_core import cli
    paths = _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")  # incomplete on its own
    defer_path = _defer_file(paths)
    defer_path.parent.mkdir(parents=True, exist_ok=True)
    defer_path.write_text(json.dumps({"deferred_at": now_iso()}))  # no "reason" key

    rc = cli.main(["close-check", "--root", str(tmp_path), "--json"])
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert rc == 1  # did not crash, did not silently pass
    assert "reason" in captured.err.lower()  # fix-round-2: warning still fires (Ruling 26)
    assert out["state"] == "incomplete"
    assert "satisfied_by" not in out


def test_close_check_defer_empty_reason_does_not_satisfy(tmp_path, capsys):
    """Same ruling, different malformation: 'reason' present but blank."""
    from omx_core import cli
    paths = _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    defer_path = _defer_file(paths)
    defer_path.parent.mkdir(parents=True, exist_ok=True)
    defer_path.write_text(json.dumps({"deferred_at": now_iso(), "reason": "   "}))

    rc = cli.main(["close-check", "--root", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert "satisfied_by" not in out


# --- close-check rescued by a fresh remote receipt (via close-ack) ----------

def test_close_check_rescued_by_a_remote_receipt(tmp_path, capsys):
    """Ruling 29 (task-5 fix-round-2): never-created is now `checked` on its
    own, so it would never even reach the receipt-rescue path (that path only
    fires on incomplete/unreadable) -- use a genuinely unreadable fixture (a
    FILE where a directory was declared) so this test still exercises what it
    says it does."""
    from omx_core import cli
    _setup(tmp_path, output_root="not-a-dir")
    (tmp_path / "not-a-dir").write_text("nope")  # unreadable locally by construction
    payload = {"state": "checked", "runs": ["runs/alpha"], "missing": [], "subject_count": 1,
               "output_root": "/container/experiments", "how": "eval.py --run {run}", "reason": None,
               "root": "/container/project", "checked_at": now_iso()}
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload))
    cli.main(["close-ack", "--root", str(tmp_path), "--from", str(payload_path)])
    capsys.readouterr()

    rc = cli.main(["close-check", "--root", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["state"] == "unreadable"  # locally, the tree is still unreadable
    assert out["satisfied_by"]["via"] == "receipt"
    assert out["satisfied_by"]["source"] == "remote"


def test_close_check_human_pass_via_receipt_names_the_origin_root(tmp_path, capsys):
    """Ruling 29 (task-5 fix-round-2): same fixture swap as the test above --
    a receipt only rescues a genuinely incomplete/unreadable local state."""
    from omx_core import cli
    _setup(tmp_path, output_root="not-a-dir")
    (tmp_path / "not-a-dir").write_text("nope")
    payload = {"state": "checked", "runs": [], "root": "/container/project", "checked_at": now_iso()}
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload))
    cli.main(["close-ack", "--root", str(tmp_path), "--from", str(payload_path)])
    capsys.readouterr()
    rc = cli.main(["close-check", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "/container/project" in out
    assert "receipt" in out.lower()


# --- close-check is NOT fooled by a stale or foreign receipt -----------------

def test_close_check_not_rescued_by_a_stale_local_receipt(tmp_path, capsys):
    from omx_core import cli
    paths = _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")  # incomplete
    old = (parse_iso_utc(now_iso(), "now") - timedelta(hours=13)).isoformat()
    write_receipt(paths, {"state": "checked", "runs": []}, source="local", now_iso=old)
    rc = cli.main(["close-check", "--root", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert "satisfied_by" not in out


def test_close_check_not_rescued_by_a_local_receipt_copied_from_another_root(tmp_path, capsys):
    """design §5's own reproduction: a `checked` receipt file copied in from a
    different project's store must not satisfy this one just because its
    content parses fine."""
    from omx_core import cli
    paths = _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")  # incomplete
    write_receipt(paths, {"state": "checked", "runs": ["runs/x"]}, source="local", now_iso=now_iso())
    receipt_path = _receipt_file(paths)
    data = json.loads(receipt_path.read_text())
    data["root"] = "/some/other/project"
    receipt_path.write_text(json.dumps(data))

    rc = cli.main(["close-check", "--root", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert "satisfied_by" not in out


# --- close-ack ----------------------------------------------------------------

def test_close_ack_accepts_checked_payload_from_file(tmp_path, capsys):
    from omx_core import cli
    paths = _setup(tmp_path)
    payload = {"state": "checked", "runs": ["runs/alpha"], "missing": [], "subject_count": 1,
               "output_root": "/container/experiments", "how": "eval.py --run {run}", "reason": None,
               "root": "/container/project", "checked_at": now_iso()}
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload))
    rc = cli.main(["close-ack", "--root", str(tmp_path), "--from", str(payload_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "/container/project" in out  # requirement 6: printed before storing

    receipt = read_receipt(paths)
    assert receipt["state"] == "checked"
    assert receipt["source"] == "remote"
    assert receipt["origin_root"] == "/container/project"
    assert receipt["root"] == str(tmp_path)  # local identity, never the far side (requirement 5)
    assert receipt["runs_checked"] == 1
    assert receipt["checked_at"] == payload["checked_at"]


def test_close_ack_accept_message_shows_reason_when_present(tmp_path, capsys):
    """N2 (task-5 fix-round-4): close-ack's accept line was dropping the
    payload's `reason` while its own refusal branch already prints it, so an
    operator accepting a Ruling-29 missing-output_root pass (a genuine
    `checked` state that still carries a distinct reason) saw a pass they
    could not interpret. Assert the two accept outputs literally DIFFER --
    not merely that one contains the reason text, which would still pass if
    both grew the same fixed suffix."""
    from omx_core import cli
    _setup(tmp_path)

    # same checked_at for both -- the ONLY difference between the two
    # payloads must be `reason`. Two separate now_iso() calls would make the
    # printed lines differ on timestamp alone, a confound that would let this
    # test pass even if the reason itself were never shown.
    checked_at = now_iso()
    payload_no_reason = {"state": "checked", "runs": [], "root": "/container/project",
                          "checked_at": checked_at}
    p1 = tmp_path / "p1.json"
    p1.write_text(json.dumps(payload_no_reason))
    rc1 = cli.main(["close-ack", "--root", str(tmp_path), "--from", str(p1)])
    out_no_reason = capsys.readouterr().out

    payload_with_reason = {"state": "checked", "runs": [], "root": "/container/project",
                            "checked_at": checked_at,
                            "reason": "output_root does not exist yet: /container/experiments"}
    p2 = tmp_path / "p2.json"
    p2.write_text(json.dumps(payload_with_reason))
    rc2 = cli.main(["close-ack", "--root", str(tmp_path), "--from", str(p2)])
    out_with_reason = capsys.readouterr().out

    assert rc1 == 0 and rc2 == 0
    assert out_no_reason != out_with_reason
    assert "does not exist" in out_with_reason
    assert "does not exist" not in out_no_reason


def test_close_ack_reads_stdin(tmp_path, capsys, monkeypatch):
    import io

    from omx_core import cli
    paths = _setup(tmp_path)
    payload = {"state": "checked", "runs": [], "root": "/container/project", "checked_at": now_iso()}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = cli.main(["close-ack", "--root", str(tmp_path), "--from", "-"])
    capsys.readouterr()
    assert rc == 0
    assert read_receipt(paths)["source"] == "remote"


def test_close_ack_refuses_incomplete_payload(tmp_path, capsys):
    from omx_core import cli
    _setup(tmp_path)
    payload = {"state": "incomplete", "runs": [], "reason": None,
               "root": "/container/project", "checked_at": now_iso()}
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload))
    rc = cli.main(["close-ack", "--root", str(tmp_path), "--from", str(payload_path)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "incomplete" in err
    assert read_receipt(OmxPaths(root=tmp_path)) is None


def test_close_ack_refuses_unreadable_payload_and_names_its_reason(tmp_path, capsys):
    from omx_core import cli
    _setup(tmp_path)
    payload = {"state": "unreadable", "runs": [], "reason": "cannot list /container/experiments: boom",
               "root": "/container/project", "checked_at": now_iso()}
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload))
    rc = cli.main(["close-ack", "--root", str(tmp_path), "--from", str(payload_path)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "boom" in err  # the reason isn't paraphrased away here either


def test_close_ack_refuses_malformed_json_without_traceback(tmp_path, capsys):
    from omx_core import cli
    _setup(tmp_path)
    payload_path = tmp_path / "payload.json"
    payload_path.write_text("{not valid json")
    rc = cli.main(["close-ack", "--root", str(tmp_path), "--from", str(payload_path)])
    err = capsys.readouterr().err
    assert rc == 2
    assert err


def test_close_ack_refuses_a_payload_that_is_not_a_verdict_shape(tmp_path, capsys):
    from omx_core import cli
    _setup(tmp_path)
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps({"hello": "world"}))
    rc = cli.main(["close-ack", "--root", str(tmp_path), "--from", str(payload_path)])
    err = capsys.readouterr().err
    assert rc == 2
    assert err


def test_close_ack_refuses_a_missing_file(tmp_path, capsys):
    from omx_core import cli
    _setup(tmp_path)
    rc = cli.main(["close-ack", "--root", str(tmp_path), "--from", str(tmp_path / "nope.json")])
    err = capsys.readouterr().err
    assert rc == 2
    assert err


def test_close_ack_refuses_stale_payload_with_a_distinguishable_message(tmp_path, capsys):
    from omx_core import cli
    _setup(tmp_path)
    old = (parse_iso_utc(now_iso(), "now") - timedelta(hours=13)).isoformat()
    payload = {"state": "checked", "runs": [], "root": "/container/project", "checked_at": old}
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload))
    rc = cli.main(["close-ack", "--root", str(tmp_path), "--from", str(payload_path)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "stale" in err.lower()
    assert "incomplete" not in err  # distinct from the state-refusal wording


def test_close_ack_never_trusts_an_incoming_source_field(tmp_path, capsys):
    """requirement 5: a payload claiming source: local is still stamped remote."""
    from omx_core import cli
    paths = _setup(tmp_path)
    payload = {"state": "checked", "runs": [], "root": str(tmp_path), "checked_at": now_iso(),
               "source": "local"}
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload))
    rc = cli.main(["close-ack", "--root", str(tmp_path), "--from", str(payload_path)])
    capsys.readouterr()
    assert rc == 0
    assert read_receipt(paths)["source"] == "remote"


def test_close_ack_refuses_a_payload_with_no_root_and_stores_nothing(tmp_path, capsys):
    """fix-round-1 reviewer finding 1: a payload missing 'root' entirely (or
    holding an empty string) must be refused with a distinct message, not
    accepted with a receipt whose origin_root key is silently absent -- which
    would later make close-check print 'satisfied by a remote receipt for
    None', the exact two-states-one-spelling defect this round exists to
    close. Checked live and confirmed the fix breaks none of this file's
    existing payload literals: every one already carries a non-empty 'root'."""
    from omx_core import cli
    _setup(tmp_path)
    payload = {"state": "checked", "runs": ["runs/alpha"], "checked_at": now_iso()}  # no "root"
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload))
    rc = cli.main(["close-ack", "--root", str(tmp_path), "--from", str(payload_path)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "root" in err.lower()
    assert "not 'checked'" not in err  # distinct from the state-refusal wording
    assert read_receipt(OmxPaths(root=tmp_path)) is None


def test_close_ack_refuses_empty_string_root_too(tmp_path, capsys):
    from omx_core import cli
    _setup(tmp_path)
    payload = {"state": "checked", "runs": [], "root": "", "checked_at": now_iso()}
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload))
    rc = cli.main(["close-ack", "--root", str(tmp_path), "--from", str(payload_path)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "root" in err.lower()
    assert read_receipt(OmxPaths(root=tmp_path)) is None


def test_close_ack_refuses_no_contract_payload_without_calling_it_a_failure(tmp_path, capsys):
    """fix-round-1 controller finding B: no-contract is an exit-0 PASS on the
    remote side. Refusing to ack it is still correct (there is nothing to
    carry back), but the message must not call it a failure -- that wording
    stays reserved for incomplete/unreadable, where it's accurate."""
    from omx_core import cli
    _setup(tmp_path)
    payload = {"state": "no-contract", "runs": [], "root": "/container/project",
               "checked_at": now_iso()}
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload))
    rc = cli.main(["close-ack", "--root", str(tmp_path), "--from", str(payload_path)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "no-contract" in err
    assert "acking a failure" not in err
    assert read_receipt(OmxPaths(root=tmp_path)) is None


# --- close-defer ---------------------------------------------------------------

def test_close_defer_writes_defer_and_exits_0(tmp_path, capsys):
    from omx_core import cli
    paths = _setup(tmp_path)
    rc = cli.main(["close-defer", "--root", str(tmp_path), "--reason", "waiting on hardware"])
    capsys.readouterr()
    assert rc == 0
    defer = read_defer(paths)
    assert defer["reason"] == "waiting on hardware"


def test_close_defer_empty_reason_is_refused(tmp_path, capsys):
    from omx_core import cli
    paths = _setup(tmp_path)
    rc = cli.main(["close-defer", "--root", str(tmp_path), "--reason", "   "])
    capsys.readouterr()
    assert rc == 2
    assert read_defer(paths) is None


def test_close_defer_reason_is_required_by_argparse(tmp_path, capsys):
    """cli.main() catches argparse's own SystemExit(2) and returns the rc
    directly (same convention every other verb test in this repo relies on) --
    it never propagates out of main()."""
    from omx_core import cli
    _setup(tmp_path)
    rc = cli.main(["close-defer", "--root", str(tmp_path)])
    capsys.readouterr()
    assert rc != 0
