"""Unit tests for omx_paths — the OMX path single-source-of-truth.

Claude-free, Isaac-free, profile-free. Pure stdlib + pytest.
"""
from omx_core.omx_paths import OmxPathError


def test_error_type_is_valueerror_subclass():
    assert issubclass(OmxPathError, ValueError)
