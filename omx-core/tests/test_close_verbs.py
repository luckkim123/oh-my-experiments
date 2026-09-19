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
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["state"] == "incomplete"
    assert out["missing"][0]["run"] == "runs/alpha"


def test_close_check_unreadable_exits_2(tmp_path, capsys):
    from omx_core import cli
    _setup(tmp_path, output_root="never-created")
    rc = cli.main(["close-check", "--root", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert out["state"] == "unreadable"
    assert out["reason"]  # requirement 2: reason surfaces, not paraphrased away


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
    from omx_core import cli
    _setup(tmp_path, output_root="never-created")
    rc = cli.main(["close-check", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 2
    assert "never-created" in out


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
    from omx_core import cli
    _setup(tmp_path)
    (tmp_path / "experiments" / "runs" / "unfinished").mkdir(parents=True)
    cli.main(["close-check", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert "1" in out


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


# --- close-check rescued by a fresh remote receipt (via close-ack) ----------

def test_close_check_rescued_by_a_remote_receipt(tmp_path, capsys):
    from omx_core import cli
    _setup(tmp_path, output_root="never-created")  # unreadable locally by construction
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
    from omx_core import cli
    _setup(tmp_path, output_root="never-created")
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
