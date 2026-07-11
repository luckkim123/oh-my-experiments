"""omx_core.cardcheck — the cross-repo card-currency guard (D-R5-4).

test_version_sync guards the in-repo plugin.json <-> pyproject fan-out, but the
omha CARD (in a DIFFERENT repo) drifted to 0.1.0 across five releases with a
pre-wiki description and nothing watched it. `omx card-check` detects the drift
at release time. It DETECTS only — updating the card is an omha-repo edit outside
R5's release scope (surfaced in the release report, not pushed from this train).

Card resolution ladder:   --card flag -> OMX_CARD_PATH env -> documented default
  ~/.claude/plugins/marketplaces/heroacademia/cards/omx.json
Plugin resolution is card-check's OWN (critic F3: doctor never reads plugin.json
and its plugin_root has no fallback):  --plugin-root -> CLAUDE_PLUGIN_ROOT ->
repo-root fallback Path(__file__).resolve().parents[2]/.claude-plugin/plugin.json
(the editable install puts __file__ in the repo, so release machines resolve with
no env). Loud-fail (OmxError) if no plugin.json is found at the ladder end.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from omx_core.omx_paths import OmxError

DEFAULT_CARD = "~/.claude/plugins/marketplaces/heroacademia/cards/omx.json"


def resolve_card_path(explicit=None) -> Path:
    """--card flag -> OMX_CARD_PATH env -> documented default."""
    raw = explicit or os.environ.get("OMX_CARD_PATH") or DEFAULT_CARD
    return Path(raw).expanduser()


def resolve_plugin_json(plugin_root=None) -> Path:
    """--plugin-root -> CLAUDE_PLUGIN_ROOT -> repo-root fallback. Loud-fail if no
    plugin.json is found at the ladder end (a release machine must fail loudly)."""
    root = plugin_root or os.environ.get("CLAUDE_PLUGIN_ROOT")
    if root:
        candidate = Path(root).expanduser() / ".claude-plugin" / "plugin.json"
    else:
        # repo-root fallback: this file is omx-core/omx_core/cardcheck.py, so the
        # repo root is parents[2] (test_version_sync.py idiom).
        candidate = Path(__file__).resolve().parents[2] / ".claude-plugin" / "plugin.json"
    if not candidate.is_file():
        raise OmxError(
            f"plugin.json not found at {candidate}; pass --plugin-root or set "
            "CLAUDE_PLUGIN_ROOT (the repo-root fallback needs an editable install)")
    return candidate


def run_card_check(*, card_path=None, plugin_root=None) -> dict:
    """Compare the omha card against the in-repo plugin.json.

    Returns {ok, card_version, plugin_version, failures}. Loud-fail (OmxError) when
    the card file is absent (actionable message) or plugin.json is unresolvable.
    Checks: (1) card.version == plugin.json.version; (2) every plugin skill's BARE
    NAME (basename of a './skills/<name>/' path) appears as a substring somewhere
    in the card JSON text (the card's own skills array is a routing-lane list, not
    a plugin-skill list, so substring presence is the honest schema-agnostic
    contract — the live card's triggers.skills carries the exact bare names)."""
    card_path = Path(card_path) if card_path is not None else resolve_card_path()
    if not card_path.is_file():
        raise OmxError(
            f"card not found at {card_path}; pass --card or set OMX_CARD_PATH "
            "(card-check runs at release time, where the card must be reachable)")
    plugin_json = resolve_plugin_json(plugin_root)

    card_text = card_path.read_text(encoding="utf-8")
    try:
        card = json.loads(card_text)
    except ValueError as e:
        raise OmxError(f"card at {card_path} is not valid JSON: {e}") from e
    try:
        plugin = json.loads(plugin_json.read_text(encoding="utf-8"))
    except ValueError as e:
        raise OmxError(f"plugin.json at {plugin_json} is not valid JSON: {e}") from e

    failures = []
    cv, pv = card.get("version"), plugin.get("version")
    if cv != pv:
        failures.append(f"version drift: card {cv!r} != plugin {pv!r}")

    for skill_path in plugin.get("skills", []):
        # './skills/exp-init/' -> 'exp-init' (basename-strip, critic F3)
        name = Path(str(skill_path).rstrip("/")).name
        if name and name not in card_text:
            failures.append(f"plugin skill {name!r} not mentioned in the card")

    return {
        "ok": not failures,
        "card_version": cv,
        "plugin_version": pv,
        "failures": failures,
    }
