"""D-R5-4: `omx card-check` guards the cross-repo card copy. test_version_sync
guards the in-repo fan-out (plugin.json <-> pyproject); nothing watched the omha
card, which is live at 0.1.0 across five releases. This verb detects the drift;
updating the card is an omha-repo edit outside R5's release scope."""
import json

import pytest
from omx_core import cli
from omx_core.cardcheck import run_card_check


def _plugin(tmp_path, version="0.6.0", skills=("./skills/exp-init/", "./skills/exp-analyze/")):
    root = tmp_path / "plugin"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "oh-my-experiments", "version": version, "skills": list(skills),
    }))
    return root


def _card(tmp_path, version="0.6.0", skill_names=("exp-init", "exp-analyze")):
    tmp_path.mkdir(parents=True, exist_ok=True)
    card = tmp_path / "omx.json"
    card.write_text(json.dumps({
        "name": "oh-my-experiments", "version": version,
        "triggers": {"skills": list(skill_names)},
    }))
    return card


def test_parity_returns_ok(tmp_path):
    out = run_card_check(card_path=_card(tmp_path), plugin_root=_plugin(tmp_path))
    assert out["ok"] is True
    assert out["card_version"] == "0.6.0"


def test_version_drift_fails_with_row(tmp_path):
    out = run_card_check(card_path=_card(tmp_path, version="0.1.0"),
                         plugin_root=_plugin(tmp_path, version="0.6.0"))
    assert out["ok"] is False
    assert any("version" in f.lower() for f in out["failures"])
    assert any("0.1.0" in f and "0.6.0" in f for f in out["failures"])


def test_missing_skill_mention_fails(tmp_path):
    # plugin declares exp-design but the card never mentions the bare name
    out = run_card_check(
        card_path=_card(tmp_path, skill_names=("exp-init",)),
        plugin_root=_plugin(tmp_path, skills=("./skills/exp-init/", "./skills/exp-design/")))
    assert out["ok"] is False
    assert any("exp-design" in f for f in out["failures"])


def test_absent_card_is_actionable(tmp_path):
    with pytest.raises(Exception) as ei:   # OmxError -> loud-fail
        run_card_check(card_path=tmp_path / "nope.json", plugin_root=_plugin(tmp_path))
    msg = str(ei.value)
    assert "card not found" in msg and ("--card" in msg or "OMX_CARD_PATH" in msg)


def test_absent_plugin_json_is_actionable(tmp_path):
    with pytest.raises(Exception) as ei:
        run_card_check(card_path=_card(tmp_path), plugin_root=tmp_path / "no-plugin")
    assert "plugin.json" in str(ei.value)


def test_malformed_card_is_actionable_rc2(tmp_path, capsys):
    card = tmp_path / "omx.json"
    card.write_text("{not json")
    rc = cli.main(["card-check", "--card", str(card),
                   "--plugin-root", str(_plugin(tmp_path))])
    err = capsys.readouterr().err
    assert rc == 2 and "not valid JSON" in err


def test_malformed_plugin_json_is_actionable_rc2(tmp_path, capsys):
    plugin_root = _plugin(tmp_path)
    (plugin_root / ".claude-plugin" / "plugin.json").write_text("{not json")
    rc = cli.main(["card-check", "--card", str(_card(tmp_path)),
                   "--plugin-root", str(plugin_root)])
    err = capsys.readouterr().err
    assert rc == 2 and "not valid JSON" in err


def test_cli_card_check_rc0_on_parity(tmp_path, capsys):
    rc = cli.main(["card-check", "--card", str(_card(tmp_path)),
                   "--plugin-root", str(_plugin(tmp_path))])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["ok"] is True


def test_cli_card_check_rc2_on_drift(tmp_path, capsys):
    rc = cli.main(["card-check", "--card", str(_card(tmp_path, version="0.1.0")),
                   "--plugin-root", str(_plugin(tmp_path, version="0.6.0"))])
    assert rc == 2


def test_env_var_precedence_for_card(tmp_path, monkeypatch, capsys):
    # OMX_CARD_PATH is used when --card is omitted
    card = _card(tmp_path)
    monkeypatch.setenv("OMX_CARD_PATH", str(card))
    rc = cli.main(["card-check", "--plugin-root", str(_plugin(tmp_path))])
    assert rc == 0


def test_flag_beats_env_for_card(tmp_path, monkeypatch, capsys):
    good = _card(tmp_path)                                   # parity 0.6.0
    bad = _card(tmp_path / "bad", version="0.1.0")           # drift
    monkeypatch.setenv("OMX_CARD_PATH", str(bad))
    rc = cli.main(["card-check", "--card", str(good),
                   "--plugin-root", str(_plugin(tmp_path))])
    assert rc == 0   # --card (good) wins over OMX_CARD_PATH (bad)


def test_repo_root_fallback_resolves(tmp_path, capsys):
    # with NO --plugin-root and NO env, the repo-root fallback must resolve the
    # REAL in-repo plugin.json (the editable install puts __file__ in the repo).
    import os
    monkeypatch_env = os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
    try:
        rc = cli.main(["card-check", "--card", str(_card(tmp_path,
                       version=json.loads((__import__("pathlib").Path(
                           __file__).resolve().parents[2] / ".claude-plugin"
                           / "plugin.json").read_text())["version"]))])
        # parity against whatever the in-repo plugin.json currently says
        assert rc in (0, 2)   # resolves without raising 'plugin.json not found'
        assert "plugin.json" not in capsys.readouterr().err or rc == 0
    finally:
        if monkeypatch_env is not None:
            os.environ["CLAUDE_PLUGIN_ROOT"] = monkeypatch_env
