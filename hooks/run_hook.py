#!/usr/bin/env python3
"""omx hook runner — fail-open dispatcher (spec 3.1, OMC run.cjs pattern in Python).

Contract: ANY exception, timeout (3s SIGALRM budget), or malformed input exits 0
with no output — a broken hook degrades to v0.1 (hookless) behavior, never blocks
work. Every guarantee a handler enforces is duplicated in a loud-fail `omx` CLI
verb; hooks are an enforcement/visibility layer on top (D9).

Kill switches:
  OMX_DISABLE=1            -> all omx hooks no-op
  OMX_SKIP_HOOKS=a,b       -> named handlers no-op

stdlib-only at import time; handlers that want omx_core import it lazily and
fall back safely when it is missing (hooks must work before `omx doctor` passes).
"""
import json
import os
import signal
import sys

_TIMEOUT_S = 3


def _ping(payload):
    """Skeleton smoke handler (kept: cheap liveness probe for doctor/tests)."""
    return {"pong": True}


def _handlers():
    table = {"ping": _ping}
    try:
        import handlers as _h  # hooks/handlers.py (Task 6+)
        table.update(_h.HANDLERS)
    except Exception:
        pass  # fail-open: no handler module -> only ping
    return table


def main() -> int:
    if os.environ.get("OMX_DISABLE") == "1":
        return 0
    if len(sys.argv) < 2:
        return 0
    name = sys.argv[1]
    skip = {s.strip() for s in os.environ.get("OMX_SKIP_HOOKS", "").split(",") if s.strip()}
    if name in skip:
        return 0
    try:
        signal.alarm(_TIMEOUT_S)
        payload = json.load(sys.stdin)
        handler = _handlers().get(name)
        if handler is None:
            return 0
        decision = handler(payload)
        if decision is not None:
            print(json.dumps(decision))
    except BaseException:
        return 0  # fail-open, always
    finally:
        signal.alarm(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
