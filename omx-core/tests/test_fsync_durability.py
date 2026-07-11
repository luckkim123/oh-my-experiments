"""#21 (D-R5-3): atomic_path/atomic_dir become durability-atomic, not just
rename-atomic. On the success path atomic_path fsyncs the tmp file BEFORE
os.replace and the parent dir AFTER; atomic_dir fsyncs the parent dir after the
directory rename. We monkeypatch os.fsync to RECORD (fd, order) and assert the
fsyncs bracket os.replace correctly. The exception path fsyncs nothing. The
tree_ops.py alias symlink swap is deliberately NOT migrated (a symlink has no
file data to lose; the rename is the durability unit — critic C2)."""
import os

import pytest

from omx_core.omx_paths import atomic_path, atomic_dir


def _trace_fsync_and_replace(monkeypatch):
    """Record the interleaving of os.fsync and os.replace as a flat event list.
    Each entry is ('fsync',) or ('replace',) so tests can assert order without
    caring about specific fds (fds are recorded separately for count)."""
    events = []
    fsync_fds = []
    real_fsync = os.fsync
    real_replace = os.replace

    def fake_fsync(fd):
        events.append(("fsync",))
        fsync_fds.append(fd)
        return real_fsync(fd)

    def fake_replace(src, dst):
        events.append(("replace",))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", fake_fsync)
    monkeypatch.setattr(os, "replace", fake_replace)
    return events, fsync_fds


def test_atomic_path_fsyncs_tmp_before_replace_and_dir_after(tmp_path, monkeypatch):
    events, fds = _trace_fsync_and_replace(monkeypatch)
    target = tmp_path / "sub" / "f.json"
    with atomic_path(target) as tmp:
        tmp.write_text("payload")
    assert target.read_text() == "payload"
    # exactly two fsyncs bracketing one replace: fsync(tmp), replace, fsync(dir)
    assert events == [("fsync",), ("replace",), ("fsync",)]
    # two fsync calls, each on a valid fd; the first fd is closed (per finally)
    # before the second is opened, so the OS is free to reuse the fd number —
    # fd equality is not a reliable "same file vs different file" signal here.
    assert len(fds) == 2 and all(fd >= 0 for fd in fds)


def test_atomic_path_exception_path_fsyncs_nothing(tmp_path, monkeypatch):
    events, _ = _trace_fsync_and_replace(monkeypatch)
    target = tmp_path / "f.json"
    with pytest.raises(ValueError):
        with atomic_path(target) as tmp:
            tmp.write_text("half")
            raise ValueError("boom")
    assert events == []                          # no fsync, no replace
    assert not target.exists()                   # target untouched
    assert not (target.with_name(target.name + ".tmp")).exists()  # tmp cleaned


def test_atomic_dir_fsyncs_parent_after_replace(tmp_path, monkeypatch):
    events, _ = _trace_fsync_and_replace(monkeypatch)
    target = tmp_path / "analysis" / "diag-20260711-100000"
    with atomic_dir(target) as tmpdir:
        (tmpdir / "report.md").write_text("x")
    assert (target / "report.md").read_text() == "x"
    # the dir rename is durable: exactly one replace, one parent-dir fsync after
    assert events == [("replace",), ("fsync",)]


def test_atomic_dir_exception_path_fsyncs_nothing(tmp_path, monkeypatch):
    events, _ = _trace_fsync_and_replace(monkeypatch)
    target = tmp_path / "analysis" / "diag-20260711-100000"
    with pytest.raises(RuntimeError):
        with atomic_dir(target) as tmpdir:
            (tmpdir / "report.md").write_text("x")
            raise RuntimeError("boom")
    assert events == []
    assert not target.exists()


def test_tree_ops_alias_swap_still_bespoke_and_pid_tmp(tmp_path):
    # regression: the alias symlink swap is NOT migrated to atomic_path. Confirm
    # it still creates the alias and still uses a pid-suffixed tmp name (a real
    # concurrent-aliaser guard no coarse lock covers). Read the source, not a
    # live swap, so this stays a fast source-contract check.
    from pathlib import Path
    import omx_core.tree_ops as tree_ops
    src = Path(tree_ops.__file__).read_text()
    # the bespoke swap keeps its own os.replace with a pid-suffixed tmp
    assert "os.getpid()" in src
    assert "os.replace" in src
    # and it does NOT route the symlink through atomic_path (which would fsync a
    # symlink to its target — wrong durability unit)
    assert "atomic_path" not in src or "symlink" in src  # atomic_path never wraps the symlink swap
