"""Tests for the `stage_check` Stop handler (Task 8, run-completion-gate round).

route_emit (spec 2.1) asks the assistant to print `STAGE(exp) -> <token> ·
<reason>` in its own text when a turn is experiment work; this handler reads
that back off the session transcript at Stop and blocks when a declared token
is out of the routing vocabulary, or is one of the exp-* stages whose skill
was never actually opened anywhere in the session. Loads hooks/handlers.py
directly, same pattern as test_completion_notice.py / test_loop_gate.py."""
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HANDLERS_PATH = REPO / "hooks" / "handlers.py"


def _load_handlers():
    spec = importlib.util.spec_from_file_location(
        "omx_stage_check_handlers", str(HANDLERS_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


handlers = _load_handlers()

ARROW = "→"   # -> as actually emitted by _ROUTE_CHECKPOINT
DOT = "·"      # bullet separating the token from the one-line reason


def _assistant_text(text, sidechain=False):
    return {"type": "assistant", "isSidechain": sidechain,
            "message": {"role": "assistant",
                        "content": [{"type": "text", "text": text}]}}


def _assistant_skill(skill, sidechain=False):
    return {"type": "assistant", "isSidechain": sidechain,
            "message": {"role": "assistant",
                        "content": [{"type": "tool_use", "name": "Skill",
                                    "input": {"skill": skill}}]}}


def _user_bare_string(text, sidechain=False):
    # measured shape (task-8-transcript-facts.md): 18% of user records carry
    # a bare string `content` instead of a block list -- e.g. slash-command
    # output wrapped in <local-command-caveat>.
    return {"type": "user", "isSidechain": sidechain,
            "message": {"role": "user", "content": text}}


def _write_transcript(tmp_path, records):
    p = tmp_path / "transcript.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return str(p)


def _payload(transcript_path, stop_hook_active=False):
    return {"transcript_path": transcript_path,
            "stop_hook_active": stop_hook_active,
            "session_id": "s1", "cwd": "/tmp/x"}


def test_out_of_vocabulary_token_blocks_and_lists_allowed_set(tmp_path):
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} bogus-stage {DOT} reason"),
    ])
    out = handlers.stage_check(_payload(tp))
    assert out["decision"] == "block"
    assert "bogus-stage" in out["reason"]
    for tok in ("exp-init", "exp-analyze", "exp-design", "exp-loop",
                "program", "wiki", "tree", "recipe"):
        assert tok in out["reason"]


def test_declared_exp_analyze_never_opened_blocks(tmp_path):
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} exp-analyze {DOT} reason"),
    ])
    out = handlers.stage_check(_payload(tp))
    assert out["decision"] == "block"
    assert "exp-analyze" in out["reason"]


def test_declared_and_opened_passes(tmp_path):
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} exp-analyze {DOT} reason"),
        _assistant_skill("oh-my-experiments:exp-analyze"),
    ])
    assert handlers.stage_check(_payload(tp)) is None


def test_user_bare_string_content_does_not_break_scan(tmp_path):
    tp = _write_transcript(tmp_path, [
        _user_bare_string("<local-command-caveat>slash output</local-command-caveat>"),
        _assistant_text(f"STAGE(exp) {ARROW} exp-design {DOT} reason"),
        _assistant_skill("exp-design"),
    ])
    assert handlers.stage_check(_payload(tp)) is None


def test_null_content_record_does_not_swallow_a_real_violation(tmp_path):
    # discriminating regression guard: reverting the isinstance(content, list)
    # guard makes `for b in None` raise inside the scan, which stage_check's
    # own try/except then swallows into a silent None -- indistinguishable
    # from "nothing to report" and hiding a real unopened-stage violation.
    # A record whose `content` is a bare string never triggers this (a
    # string's characters just fail the inner isinstance(b, dict) check and
    # get skipped harmlessly) -- only a missing/None content does, so this
    # is a separate case from test_user_bare_string_content_does_not_break_scan.
    tp = _write_transcript(tmp_path, [
        {"type": "user", "isSidechain": False,
         "message": {"role": "user", "content": None}},
        _assistant_text(f"STAGE(exp) {ARROW} exp-analyze {DOT} reason"),
    ])
    out = handlers.stage_check(_payload(tp))
    assert out["decision"] == "block"
    assert "exp-analyze" in out["reason"]


def test_missing_transcript_returns_none(tmp_path):
    out = handlers.stage_check(_payload(str(tmp_path / "nope.jsonl")))
    assert out is None


def test_stop_hook_active_suppresses_block(tmp_path):
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} bogus {DOT} reason"),
    ])
    assert handlers.stage_check(_payload(tp, stop_hook_active=True)) is None


def test_no_stage_line_returns_none(tmp_path):
    tp = _write_transcript(tmp_path, [_assistant_text("just a normal reply")])
    assert handlers.stage_check(_payload(tp)) is None


def test_sidechain_skill_open_does_not_count(tmp_path):
    # a subagent opening exp-loop's own skill must not count as the main
    # session having opened it (task-8-transcript-facts.md: isSidechain).
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} exp-loop {DOT} reason"),
        _assistant_skill("exp-loop", sidechain=True),
    ])
    out = handlers.stage_check(_payload(tp))
    assert out["decision"] == "block"
    assert "exp-loop" in out["reason"]


def test_non_skill_vocab_token_needs_no_open(tmp_path):
    # program/wiki/tree/recipe are vocabulary members but not exp-* skills.
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} wiki {DOT} reason"),
    ])
    assert handlers.stage_check(_payload(tp)) is None


def test_corrupt_json_line_does_not_abort_scan(tmp_path):
    tp = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps(_assistant_text(f"STAGE(exp) {ARROW} exp-init {DOT} reason")),
        "{not valid json",
        json.dumps(_assistant_skill("exp-init")),
    ]
    tp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert handlers.stage_check(_payload(str(tp))) is None


def test_only_unopened_stage_named_in_block_reason(tmp_path):
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} exp-design {DOT} r1"),
        _assistant_skill("exp-design"),
        _assistant_text(f"STAGE(exp) {ARROW} exp-analyze {DOT} r2"),
    ])
    out = handlers.stage_check(_payload(tp))
    assert out["decision"] == "block"
    assert "exp-analyze" in out["reason"]
    assert "exp-design" not in out["reason"]
