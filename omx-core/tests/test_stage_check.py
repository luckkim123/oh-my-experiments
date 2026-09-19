"""Tests for the `stage_check` Stop handler (Task 8, run-completion-gate round).

route_emit (spec 2.1) asks the assistant to print `STAGE(exp) -> <token> ·
<reason>` in its own text when a turn is experiment work; this handler reads
that back off the session transcript at Stop and blocks when the session's
CURRENT (most recent, assistant-authored) declaration names one of the exp-*
stages whose skill was never actually opened anywhere in the session. Loads
hooks/handlers.py directly, same pattern as test_completion_notice.py /
test_loop_gate.py.

fix-round-1 (task-8-review Finding 1/2, Rulings 33-34): the vocabulary-
mismatch block was withdrawn (an unparseable or unrecognized token is never a
violation by itself -- only a cleanly-parsed exp-* token whose skill was
never opened blocks), the declared side collapsed from a lifetime set to
"latest declaration only", and the scan now reads assistant-authored content
only. Tests below cover the real markdown shapes the reviewer measured in
production transcripts (bold STAGE lines, a bold arrow-only prefix, glued
punctuation), not just the canonical one."""
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


def _assistant_bash(command, sidechain=False):
    return {"type": "assistant", "isSidechain": sidechain,
            "message": {"role": "assistant",
                        "content": [{"type": "tool_use", "name": "Bash",
                                    "input": {"command": command}}]}}


def _user_text(text, sidechain=False):
    return {"type": "user", "isSidechain": sidechain,
            "message": {"role": "user",
                        "content": [{"type": "text", "text": text}]}}


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


# --- canonical + real-shape declarations, skill genuinely opened -> pass ---

def test_declared_and_opened_passes(tmp_path):
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} exp-analyze {DOT} reason"),
        _assistant_skill("oh-my-experiments:exp-analyze"),
    ])
    assert handlers.stage_check(_payload(tp)) is None


def test_bold_whole_line_declaration_still_parses_and_passes(tmp_path):
    # measured in production: an assistant bolds the STAGE line the same way
    # it already bolds the ROUTE line above it. The bold markers sit OUTSIDE
    # "-> exp-analyze", so extraction is unaffected.
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"**STAGE(exp) {ARROW} exp-analyze {DOT} reason**"),
        _assistant_skill("exp-analyze"),
    ])
    assert handlers.stage_check(_payload(tp)) is None


def test_ascii_arrow_declaration_still_parses_and_passes(tmp_path):
    tp = _write_transcript(tmp_path, [
        _assistant_text("STAGE(exp) -> exp-design · reason"),
        _assistant_skill("exp-design"),
    ])
    assert handlers.stage_check(_payload(tp)) is None


# --- Ruling 33: an unparseable/unrecognized token is NEVER a violation -----
# (inverted from fix-round-0's test_out_of_vocabulary_token_blocks_and_lists_
# allowed_set, which asserted the withdrawn behavior -- see docstring above).

def test_out_of_vocabulary_token_no_longer_blocks(tmp_path):
    """Fix-round-1, Ruling 33 -- reverses fix-round-0's
    test_out_of_vocabulary_token_blocks_and_lists_allowed_set, which asserted
    a `block` here. The vocabulary-mismatch check is withdrawn entirely: it
    cannot tell "the session invented a stage name" apart from "we failed to
    parse this line" (both arrive as a string outside _STAGE_SKILL_TOKENS),
    and guessing wrong traps the operator in a Stop hook with no escape. Same
    fixture as before, opposite verdict."""
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} bogus-stage {DOT} reason"),
    ])
    assert handlers.stage_check(_payload(tp)) is None


def test_bold_arrow_only_prefix_garbage_capture_does_not_block(tmp_path):
    # the reviewer's Finding-1 reproduction: bolding stops right after the
    # arrow ("**STAGE(exp) →**"), so extraction captures "**" instead of
    # "exp-analyze". Skill genuinely never opened -- under the withdrawn
    # vocabulary check this blocked; under Ruling 33 it must not, because a
    # mis-extraction and an invented token cannot be told apart.
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"> **STAGE(exp) {ARROW}** exp-analyze {DOT} reason"),
    ])
    assert handlers.stage_check(_payload(tp)) is None


def test_missing_exp_prefix_glued_colon_does_not_block(tmp_path):
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} analyze: reason"),
    ])
    assert handlers.stage_check(_payload(tp)) is None


def test_trailing_period_no_bullet_does_not_block(tmp_path):
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} exp-analyze."),
    ])
    assert handlers.stage_check(_payload(tp)) is None


# --- Ruling 34: only the LATEST declaration is checked ---------------------

def test_declared_exp_analyze_never_opened_blocks(tmp_path):
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} exp-analyze {DOT} reason"),
    ])
    out = handlers.stage_check(_payload(tp))
    assert out["decision"] == "block"
    assert "exp-analyze" in out["reason"]


def test_only_the_latest_declaration_is_named_when_blocking(tmp_path):
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} exp-design {DOT} r1"),
        _assistant_skill("exp-design"),
        _assistant_text(f"STAGE(exp) {ARROW} exp-analyze {DOT} r2"),
    ])
    out = handlers.stage_check(_payload(tp))
    assert out["decision"] == "block"
    assert "exp-analyze" in out["reason"]
    assert "exp-design" not in out["reason"]


def test_a_superseding_correct_declaration_clears_an_earlier_garbage_one(tmp_path):
    # fix-round-0 regression, confirmed live: a bad early line poisoned a
    # lifetime set, so a later CORRECT declaration whose skill WAS opened
    # still blocked. Ruling 34 fixes this structurally -- only the latest
    # declaration is ever checked, so the garbage line is simply superseded.
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"> **STAGE(exp) {ARROW}** exp-analyze {DOT} garbage capture"),
        _assistant_text(f"STAGE(exp) {ARROW} exp-design {DOT} the real one"),
        _assistant_skill("exp-design"),
    ])
    assert handlers.stage_check(_payload(tp)) is None


def test_a_superseding_declaration_un_declares_an_earlier_unopened_one(tmp_path):
    # the session declared exp-analyze, never opened it, then legitimately
    # moved on to exp-design and opened THAT -- the abandoned exp-analyze
    # declaration must not block forever.
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} exp-analyze {DOT} r1"),
        _assistant_text(f"STAGE(exp) {ARROW} exp-design {DOT} r2"),
        _assistant_skill("exp-design"),
    ])
    assert handlers.stage_check(_payload(tp)) is None


# --- Finding 2: only assistant-authored content counts ---------------------

def test_user_authored_stage_line_is_never_read_as_a_declaration(tmp_path):
    # a user pasting a well-formed STAGE line into their OWN message must
    # never be read as the assistant declaring it -- no assistant declaration
    # exists here at all, so this must pass regardless of vocabulary/skill.
    tp = _write_transcript(tmp_path, [
        _user_text(f"STAGE(exp) {ARROW} exp-analyze {DOT} reason"),
    ])
    assert handlers.stage_check(_payload(tp)) is None


def test_trailing_user_stage_text_does_not_override_the_real_declaration(tmp_path):
    # the assistant's real (unopened) declaration is the session's true
    # current state; a user record after it, even one shaped like a STAGE
    # line, must not become "latest" and must not change the verdict.
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} exp-analyze {DOT} r1"),
        _user_text(f"STAGE(exp) {ARROW} exp-design {DOT} not the assistant"),
    ])
    out = handlers.stage_check(_payload(tp))
    assert out["decision"] == "block"
    assert "exp-analyze" in out["reason"]


def test_user_bare_string_content_does_not_break_scan(tmp_path):
    tp = _write_transcript(tmp_path, [
        _user_bare_string("<local-command-caveat>slash output</local-command-caveat>"),
        _assistant_text(f"STAGE(exp) {ARROW} exp-design {DOT} reason"),
        _assistant_skill("exp-design"),
    ])
    assert handlers.stage_check(_payload(tp)) is None


# --- structural robustness --------------------------------------------------

def test_null_content_assistant_record_does_not_swallow_a_real_violation(tmp_path):
    # discriminating regression guard: reverting the isinstance(content, list)
    # guard makes `for b in None` raise inside the scan, which stage_check's
    # own try/except then swallows into a silent None -- indistinguishable
    # from "nothing to report" and hiding a real unopened-stage violation.
    # Must be on an ASSISTANT record (Finding 2 restricts the scan to
    # type == "assistant", so a malformed USER record is now filtered out
    # before content is ever read and can no longer exercise this guard).
    tp = _write_transcript(tmp_path, [
        {"type": "assistant", "isSidechain": False,
         "message": {"role": "assistant", "content": None}},
        _assistant_text(f"STAGE(exp) {ARROW} exp-analyze {DOT} reason"),
    ])
    out = handlers.stage_check(_payload(tp))
    assert out["decision"] == "block"
    assert "exp-analyze" in out["reason"]


def test_missing_transcript_returns_none(tmp_path):
    out = handlers.stage_check(_payload(str(tmp_path / "nope.jsonl")))
    assert out is None


def test_stop_hook_active_suppresses_a_real_violation(tmp_path):
    # must suppress a GENUINE would-be block (declared, never opened), not
    # merely a garbage token that would never block anyway post-Ruling-33.
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} exp-analyze {DOT} reason"),
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
    # program/wiki/tree/recipe are routing-vocabulary words but not skills.
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


# --- Ruling 35 (fix-round-2): CLI-verb evidence, the way work is really done

def test_distinctive_cli_verb_counts_as_opened_with_no_skill_call(tmp_path):
    # the corpus finding this round exists for: 173 exp-analyze declarations,
    # zero Skill invocations of it. `report-review` is exp-analyze-distinctive.
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} exp-analyze {DOT} reason"),
        _assistant_bash("omx report-review --root . --analysis-id x-20260919-120000"),
    ])
    assert handlers.stage_check(_payload(tp)) is None


def test_another_stages_distinctive_verb_does_not_count(tmp_path):
    # `loop-arm` is exp-loop-distinctive; it must not clear an exp-analyze
    # declaration -- CLI-verb evidence is per-stage, not blanket omx activity.
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} exp-analyze {DOT} reason"),
        _assistant_bash("omx loop-arm --run-id r1 --max-runtime-s 3600"),
    ])
    out = handlers.stage_check(_payload(tp))
    assert out["decision"] == "block"
    assert "exp-analyze" in out["reason"]


def test_shared_utility_verb_does_not_count_as_stage_evidence(tmp_path):
    # `doctor` and `wiki query` are used by every stage's SKILL.md -- they
    # are deliberately excluded from _STAGE_CLI_VERBS (see its docstring
    # comment): counting them would make the check pass on ANY omx activity
    # regardless of which stage is actually declared.
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} exp-analyze {DOT} reason"),
        _assistant_bash("omx doctor"),
        _assistant_bash('omx wiki query --root . "something"'),
    ])
    out = handlers.stage_check(_payload(tp))
    assert out["decision"] == "block"
    assert "exp-analyze" in out["reason"]


def test_verb_in_a_longer_command_still_counts(tmp_path):
    # real commands are rarely a bare verb -- they chain cd/flags/pipes.
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} exp-design {DOT} reason"),
        _assistant_bash("cd /tmp/x && omx probe-novelty --root . --probe p1 | tee out.log"),
    ])
    assert handlers.stage_check(_payload(tp)) is None


def test_sidechain_cli_verb_does_not_count(tmp_path):
    # same principle as the Skill-based isSidechain guard: a subagent running
    # a stage's verb must not count as the main session having done it.
    tp = _write_transcript(tmp_path, [
        _assistant_text(f"STAGE(exp) {ARROW} exp-loop {DOT} reason"),
        _assistant_bash("omx loop-arm --run-id r1 --max-runtime-s 3600", sidechain=True),
    ])
    out = handlers.stage_check(_payload(tp))
    assert out["decision"] == "block"
    assert "exp-loop" in out["reason"]


def test_stage_cli_verbs_are_distinctive_not_shared():
    # structural check on the constant itself: no verb should appear in more
    # than one stage's set, or CLI-verb evidence would stop discriminating
    # between stages (the same failure the vocabulary check had).
    seen = {}
    dupes = []
    for stage, verbs in handlers._STAGE_CLI_VERBS.items():
        for v in verbs:
            if v in seen:
                dupes.append((v, seen[v], stage))
            seen[v] = stage
    assert not dupes, f"non-distinctive verbs shared across stages: {dupes}"
