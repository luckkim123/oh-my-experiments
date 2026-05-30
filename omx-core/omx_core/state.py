"""omx_core.state — the single .omx/state.json mode-state file.

Build-order #1 defines the schema and atomic IO; the loop (build #6) fills the
fields. Kept minimal on purpose (YAGNI): only the keys design 10.2 names.
"""
import copy
import json

from omx_core.omx_paths import OmxPaths, atomic_path

# design 10.2: state.json holds OMX mode state (active loop?, current_phase, session_id)
DEFAULT_STATE = {
    "omx_state_version": 1,
    "active_loop": None,
    "current_phase": None,
    "session_id": None,
}


def load_state(paths: OmxPaths) -> dict:
    """Return the persisted state, or a fresh copy of DEFAULT_STATE if absent."""
    target = paths.state_json()
    if not target.exists():
        return copy.deepcopy(DEFAULT_STATE)
    return json.loads(target.read_text())


def save_state(paths: OmxPaths, state: dict) -> None:
    """Atomically write state to .omx/state.json (parents created, .tmp + os.replace)."""
    target = paths.state_json()
    target.parent.mkdir(parents=True, exist_ok=True)
    with atomic_path(target) as tmp:
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
