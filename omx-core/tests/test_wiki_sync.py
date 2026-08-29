"""sync-profile after B4 moved the projection out of the page store.

`profile.md` is regenerated from `.omx/profile/*`, which store-spec section 3
rule (4) -- "can a verb regenerate it from other files?" -- puts in the `work/`
layer, not in `community/` where posts live. So it is a plain markdown file at
`OmxPaths.profile_projection()` now, and two tests went with the store it used
to live in: `test_reserved_page_hidden_from_list_but_readable` (there is no
reserved-page concept in a post store, and `wiki read` reads posts) and
`test_hand_write_of_profile_page_blocked` (no `storage.write_page` to refuse).
The mtime contract, which is what actually kept the projection honest, is
unchanged and still checked here.
"""
import json
import os

from omx_core.cli import main
from omx_core.omx_paths import OmxPaths


def _mk_profile(tmp_path):
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "metrics.yaml").write_text("output_root: experiments\nkeep_policy: pass_only\n")
    (prof / "rules.md").write_text("# rules\n- always report CV\n")
    (prof / "evaluator.sh").write_text("echo '{\"pass\": true}'\n")
    return prof


def _projection(tmp_path):
    return OmxPaths(root=tmp_path).profile_projection()


def test_sync_writes_the_work_layer_projection(tmp_path, capsys):
    _mk_profile(tmp_path)
    rc = main(["wiki", "sync-profile", "--root", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "synced"
    page = _projection(tmp_path)
    assert out["path"] == str(page)
    assert "output_root: experiments" in page.read_text()


def test_the_projection_is_not_a_post(tmp_path, capsys):
    """A regenerable projection in the shared post store would be a machine
    artifact in a layer meant for records humans wrote (store-spec section 3,
    (4) beats (2)). It must land under work/, and never mint a post."""
    _mk_profile(tmp_path)
    main(["wiki", "sync-profile", "--root", str(tmp_path)])
    capsys.readouterr()
    page = _projection(tmp_path)
    assert ".hq/work/" in str(page) and "/posts/" not in str(page)
    assert not (tmp_path / ".hq" / "community" / "posts").exists()


def test_sync_skips_when_page_newer(tmp_path, capsys):
    prof = _mk_profile(tmp_path)
    main(["wiki", "sync-profile", "--root", str(tmp_path)])
    capsys.readouterr()
    main(["wiki", "sync-profile", "--root", str(tmp_path)])
    assert json.loads(capsys.readouterr().out)["action"] == "unchanged"
    # touch the profile forward -> re-sync
    m = prof / "metrics.yaml"
    st = m.stat()
    os.utime(m, (st.st_atime + 10, st.st_mtime + 10))
    main(["wiki", "sync-profile", "--root", str(tmp_path)])
    assert json.loads(capsys.readouterr().out)["action"] == "synced"


def test_same_second_profile_edit_still_syncs(tmp_path, capsys):
    # Same-second mtime tie must re-sync, not skip (R1 carry-over): the skip
    # condition is STRICTLY > prof_mtime, not >=.
    prof = _mk_profile(tmp_path)
    main(["wiki", "sync-profile", "--root", str(tmp_path)])
    capsys.readouterr()
    page = _projection(tmp_path)
    m = prof / "metrics.yaml"
    m.write_text(m.read_text() + "# same-second edit\n")
    tie = page.stat().st_mtime
    os.utime(m, (tie, tie))  # exact mtime tie with the already-synced page
    main(["wiki", "sync-profile", "--root", str(tmp_path)])
    assert json.loads(capsys.readouterr().out)["action"] == "synced"


def test_sync_after_seal_resyncs(tmp_path, capsys):
    # I-1: sealing after a sync (no projected-file changes) must not leave
    # the projection stuck asserting the pre-seal status forever.
    from omx_core.seal import write_seal
    _mk_profile(tmp_path)
    main(["wiki", "sync-profile", "--root", str(tmp_path)])
    capsys.readouterr()
    write_seal(OmxPaths(root=tmp_path), now="2026-07-06T00:00:00")
    # force the seal strictly newer than the page (same-second writes would
    # otherwise tie under mtime `>=`, same edge as the carried T12 minor)
    seal_fp = OmxPaths(root=tmp_path).seal_json()
    st = seal_fp.stat()
    os.utime(seal_fp, (st.st_atime + 10, st.st_mtime + 10))
    rc = main(["wiki", "sync-profile", "--root", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["action"] == "synced"
    assert "status: ok" in _projection(tmp_path).read_text()


def test_sync_loud_fails_without_profile(tmp_path, capsys):
    rc = main(["wiki", "sync-profile", "--root", str(tmp_path)])
    assert rc == 2


def test_sync_loud_fails_cleanly_when_metrics_yaml_missing(tmp_path, capsys):
    # Only evaluator.sh present (no metrics.yaml, no rules.md): the initial
    # presence check (ANY of _PROJECTED) passes, but composing the page needs
    # metrics.yaml specifically. Must exit rc 2 via a clean OmxError/SystemExit,
    # never an unhandled FileNotFoundError.
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "evaluator.sh").write_text("echo '{\"pass\": true}'\n")
    rc = main(["wiki", "sync-profile", "--root", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "metrics.yaml" in err
