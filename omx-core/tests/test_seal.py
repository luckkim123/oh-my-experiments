import json

import pytest

from omx_core.omx_paths import OmxError, OmxPaths
from omx_core.seal import check_seal, write_seal
from omx_core.cli import main


def _mk_profile(tmp_path, evaluator="echo '{\"pass\": true}'"):
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "evaluator.sh").write_text(evaluator + "\n")
    (prof / "launch.sh").write_text("echo template\n")
    return OmxPaths(root=tmp_path)


def test_seal_roundtrip(tmp_path):
    paths = _mk_profile(tmp_path)
    s = write_seal(paths, now="2026-07-05T12:00:00")
    assert set(s["file_sha256"]) == {"evaluator.sh", "launch.sh"}
    assert check_seal(paths)["status"] == "ok"


def test_seal_detects_modification(tmp_path):
    paths = _mk_profile(tmp_path)
    write_seal(paths, now="t")
    (tmp_path / ".omx" / "profile" / "evaluator.sh").write_text("echo tampered\n")
    st = check_seal(paths)
    assert st["status"] == "mismatch" and st["mismatched"] == ["evaluator.sh"]


def test_seal_absent_and_missing_evaluator(tmp_path):
    paths = _mk_profile(tmp_path)
    assert check_seal(paths)["status"] == "absent"
    bare = OmxPaths(root=tmp_path / "empty")
    with pytest.raises(OmxError, match="evaluator.sh"):
        write_seal(bare, now="t")


def test_cli_profile_seal(tmp_path, capsys):
    _mk_profile(tmp_path)
    rc = main(["profile-seal", "--root", str(tmp_path)])
    assert rc == 0
    assert "file_sha256" in json.loads(capsys.readouterr().out)


def test_eval_blocks_on_mismatch(tmp_path, capsys):
    _mk_profile(tmp_path)
    main(["profile-seal", "--root", str(tmp_path)])
    (tmp_path / ".omx" / "profile" / "evaluator.sh").write_text("echo changed\n")
    rc = main(["eval", "--command", "echo '{\"pass\": true}'", "--root", str(tmp_path)])
    assert rc == 2
    assert "profile-seal" in capsys.readouterr().err


def test_eval_warns_on_absent_seal_but_runs(tmp_path, capsys):
    _mk_profile(tmp_path)
    rc = main(["eval", "--command", "echo '{\"pass\": true}'", "--root", str(tmp_path)])
    cap = capsys.readouterr()
    assert rc == 0
    assert json.loads(cap.out)["status"] == "pass"
    assert "no profile seal" in cap.err


def test_eval_warns_when_root_omitted(capsys):
    rc = main(["eval", "--command", "echo '{\"pass\": true}'"])
    cap = capsys.readouterr()
    assert rc == 0
    assert "seal check skipped" in cap.err
