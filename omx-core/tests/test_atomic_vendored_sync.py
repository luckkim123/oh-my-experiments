from pathlib import Path

import pytest

VENDORED = Path(__file__).resolve().parent.parent / "omx_core" / "atomic.py"
CANONICAL = Path.home() / "om-core" / "atomic_ctx.py"


def test_vendored_atomic_matches_canonical():
    if not CANONICAL.exists():
        pytest.skip("om-core sibling absent (clean CI runner)")
    assert VENDORED.read_bytes() == CANONICAL.read_bytes(), \
        "atomic file drifted from om-core — re-vendor: cp ~/om-core/atomic_ctx.py <this>"
