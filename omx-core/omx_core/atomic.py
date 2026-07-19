"""om-core shared atomic-write primitive (context-manager form) — vendored
verbatim into consumer repos; edit only in om-core.

Two context managers for crash-safe promotion of a file or a directory tree:
`atomic_path` yields a '.tmp' sibling path to write into; `atomic_dir` yields a
'.tmp' sibling directory to build into. Both promote via `os.replace` on clean
exit and discard the '.tmp' on exception, and both add a parent-directory-entry
fsync on top of the file/dir-content fsync (stronger durability than the
function-form primitive in `atomic_fn.py`).
"""
import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_path(target):
    """Yield a '.tmp' sibling; on clean exit fsync(tmp) -> os.replace -> fsync(dir).

    Rename-atomic AND durability-atomic (D-R5-3, #21): before the replace the
    tmp file's data is flushed to disk (fsync on a read-only re-open of the tmp),
    and after the replace the parent directory entry is flushed (os.fsync of an
    O_RDONLY dir fd — macOS/Linux both support directory fsync). A power loss in
    the write window can no longer lose a committed ledger row. On exception the
    .tmp is removed and target is untouched, so partial artifacts never pollute
    the clean tree AND no fsync runs (design 10.1). Parent dirs created.
    Every writer (save_state, the ledger writers, the loop marker, pending-launch,
    all wiki writes) routes through here and inherits the fix for free."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    # simplified: fixed '<name>.tmp' name (NOT uuid-suffixed). Every atomic_path
    # caller that can race is serialized by a coarser lock (state mutex, wiki
    # lock, run lease); the one unserialized racer (tree alias) keeps its own
    # pid-suffixed bespoke swap. atomic_dir also relies on this fixed name for
    # leftover cleanup. Upgrade path: a uuid suffix only if a new unserialized
    # atomic_path caller ever appears.
    tmp = target.with_name(target.name + ".tmp")
    try:
        yield tmp
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise
    else:
        # flush the tmp file's DATA, then rename, then flush the directory ENTRY.
        fd = os.open(str(tmp), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, target)
        dir_fd = os.open(str(target.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


@contextmanager
def atomic_dir(target):
    """Like atomic_path but for a directory: build under '<name>.tmp/', then
    os.replace the whole dir onto target on clean exit; discard on exception.

    Linux note: os.replace onto a directory requires `target` to NOT exist or be
    empty (a non-empty existing dir raises OSError Errno 39). OMX analysis ids
    carry an HHMMSS timestamp so collisions are near-impossible; if a caller
    genuinely needs to overwrite, it must shutil.rmtree(target) first — this
    helper deliberately does NOT auto-delete an existing target (silently
    destroying prior output is a worse failure than a loud Errno 39).

    D-R5-3: the parent-dir fsync makes the rename durable, NOT the promoted
    directory's file contents (accepted ceiling, critic F7).
    """
    import shutil
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        yield tmp
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    else:
        # os.replace is OUTSIDE the except above; guard it so a failed promotion
        # (e.g. Errno 39 on a non-empty target) doesn't leak the .tmp dir.
        try:
            os.replace(tmp, target)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        # D-R5-3: parent-dir fsync makes the RENAME durable — NOT the promoted
        # directory's file CONTENTS. A power loss can still lose file data inside
        # a just-promoted analysis dir; recursively fsyncing every file is not
        # worth the IO (accepted ceiling, critic F7).
        dir_fd = os.open(str(target.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
