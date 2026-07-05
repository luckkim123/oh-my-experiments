import json
import os

from omx_core.cli import main


def _mk_profile(tmp_path):
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "metrics.yaml").write_text("output_root: experiments\nkeep_policy: pass_only\n")
    (prof / "rules.md").write_text("# rules\n- always report CV\n")
    (prof / "evaluator.sh").write_text("echo '{\"pass\": true}'\n")
    return prof


def test_sync_creates_reserved_page(tmp_path, capsys):
    _mk_profile(tmp_path)
    rc = main(["wiki", "sync-profile", "--root", str(tmp_path)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["action"] == "synced"
    page = tmp_path / ".omx" / "registry" / "findings" / "profile.md"
    body = page.read_text()
    assert "output_root: experiments" in body and "category: environment" in body


def test_reserved_page_hidden_from_list_but_readable(tmp_path, capsys):
    _mk_profile(tmp_path)
    main(["wiki", "sync-profile", "--root", str(tmp_path)])
    capsys.readouterr()
    main(["wiki", "list", "--root", str(tmp_path)])
    listed = json.loads(capsys.readouterr().out)
    assert all(p["slug"] != "profile.md" for p in listed["pages"])
    rc = main(["wiki", "read", "--root", str(tmp_path), "--slug", "profile"])
    assert rc == 0 and "output_root" in capsys.readouterr().out


def test_sync_skips_when_page_newer(tmp_path, capsys):
    prof = _mk_profile(tmp_path)
    main(["wiki", "sync-profile", "--root", str(tmp_path)])
    capsys.readouterr()
    rc = main(["wiki", "sync-profile", "--root", str(tmp_path)])
    assert json.loads(capsys.readouterr().out)["action"] == "unchanged"
    # touch the profile forward -> re-sync
    m = prof / "metrics.yaml"
    st = m.stat()
    os.utime(m, (st.st_atime + 10, st.st_mtime + 10))
    main(["wiki", "sync-profile", "--root", str(tmp_path)])
    assert json.loads(capsys.readouterr().out)["action"] == "synced"


def test_sync_loud_fails_without_profile(tmp_path, capsys):
    rc = main(["wiki", "sync-profile", "--root", str(tmp_path)])
    assert rc == 2


def test_hand_write_of_profile_page_blocked(tmp_path):
    import pytest
    from omx_core.omx_paths import OmxPaths
    from omx_core.wiki import storage
    from omx_core.wiki.types import WikiError, WikiPage
    _mk_profile(tmp_path)
    with pytest.raises(WikiError, match="reserved"):
        storage.write_page(OmxPaths(root=tmp_path),
                           WikiPage(slug="profile.md", title="x"), now="t")
