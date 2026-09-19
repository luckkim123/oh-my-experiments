"""Task 5 -- closure_guard PreToolUse Bash hook handler (design doc §4-6).

Denies a closure-declaring Bash command (`hq post --category handoff`,
`omx loop-disarm`/`loop-mark-done --reason done`) when this project's
finished training runs are missing the evaluation artifacts its own profile
declared (state "incomplete"), or when the gate could not tell at all (state
"unreadable"). Loads hooks/handlers.py directly, same pattern as
test_report_guard.py / test_hook_backlog.py.

Fixture trees mirror test_close_verbs.py's CONTRACT/_setup/_finish shape, plus
an `.omx-workspace` marker so the #13 root ladder anchors HERE (stage
"marker") instead of falling to stage "cwd" -- which `_resolve_backlog_root`
(reused by closure_guard) treats as "no omx project at all" and raises.
"""
import importlib.util
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from omx_core.clock import now_iso, parse_iso_utc
from omx_core.completion import write_defer, write_receipt
from omx_core.omx_paths import OmxPaths
from omx_core.profile import bootstrap_profile, default_metrics

REPO = Path(__file__).resolve().parents[2]
HANDLERS_PATH = REPO / "hooks" / "handlers.py"
RUNNER = REPO / "hooks" / "run_hook.py"

CONTRACT = {
    "runs": "runs/*",
    "finished": "checkpoints/*.pt",
    "exclude": ["runs/smoke-*"],
    "required": ["eval/*.json", "plots/*.png"],
    "how": "python analysis/eval.py static --run {run}",
}

CLOSURE_COMMANDS = [
    'hq post --category handoff --summary "closing out"',
    "omx loop-disarm --reason done",
    "omx loop-mark-done --reason done",
]


def _load_handlers():
    spec = importlib.util.spec_from_file_location("omx_hook_handlers_closure", str(HANDLERS_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _setup(root, run_completion=CONTRACT, output_root="experiments", anchor=True):
    root.mkdir(parents=True, exist_ok=True)
    if anchor:
        (root / ".omx-workspace").touch()
    paths = OmxPaths(root=root)
    metrics = default_metrics()
    metrics["output_root"] = output_root
    if run_completion is not None:
        metrics["run_completion"] = run_completion
    bootstrap_profile(paths, profile_name="isaaclab", metrics=metrics)
    return paths


def _setup_unreadable(root, **kwargs):
    """A genuinely-unreadable output_root (Ruling 29, task-5 fix-round-2): a
    FILE where a directory was declared. A never-created output_root is now
    `checked` (see test_missing_output_root_now_allows_a_closure_command), so
    it no longer produces `unreadable` and can't stand in for it here."""
    paths = _setup(root, output_root="not-a-dir", **kwargs)
    (root / "not-a-dir").write_text("nope")
    return paths


def _finish(run_dir):
    (run_dir / "checkpoints").mkdir(parents=True)
    (run_dir / "checkpoints" / "final.pt").write_text("x")


def _satisfy_required(run_dir):
    (run_dir / "eval").mkdir(exist_ok=True)
    (run_dir / "eval" / "summary.json").write_text("{}")
    (run_dir / "plots").mkdir(exist_ok=True)
    (run_dir / "plots" / "curve.png").write_text("x")


def _payload(command, cwd, tool_name="Bash"):
    return {"tool_name": tool_name, "tool_input": {"command": command}, "cwd": str(cwd)}


def _run(mod, command, cwd, tool_name="Bash"):
    return mod.closure_guard(_payload(command, cwd, tool_name))


# --- the three closure declarations, each denied on an incomplete fixture ---

def test_each_closure_command_denied_on_incomplete_fixture(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")  # incomplete: no eval/plots
    for command in CLOSURE_COMMANDS:
        out = _run(mod, command, tmp_path)
        assert out is not None, command
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_reason_done_also_matches_the_equals_form(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "omx loop-disarm --reason=done", tmp_path)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_category_handoff_also_matches_the_equals_form(tmp_path):
    """Ruling 28, fix-round-1: `--category=handoff` was originally missed --
    the brief scoped `=`-form handling to `--reason` only, and that scoping
    was an oversight, not a decision. A gate with a one-character `=`-form
    bypass on one flag but not another is the same hole class as the
    separator-gluing bypass closed in the first round."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "hq post --category=handoff", tmp_path)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- non-closure commands / non-Bash tools / malformed input allow ----------

def test_reason_cancel_is_not_a_closure_declaration(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    assert _run(mod, "omx loop-disarm --reason cancel", tmp_path) is None


def test_quoted_category_handoff_inside_summary_does_not_trigger(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, 'hq post --summary "see --category handoff note"', tmp_path)
    assert out is None


def test_non_bash_tools_pass(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "hq post --category handoff", tmp_path, tool_name="Read")
    assert out is None


def test_malformed_command_shlex_valueerror_denies(tmp_path):
    """Ruling 37 (Task-11 cross-model fresh-loop round-1): reverses this
    test's original assertion. The brief's own step 1 ("ValueError -> None,
    allow") was withdrawn -- a shlex tokenizer failure is a parse failure,
    the same class Ruling 30 already governs for the heredoc scanner, and
    letting it fall through to the outer fail-open turned "I could not read
    this command" into a silent allow. This round's worst finding was
    exactly that shape (an apostrophe in an ordinary comment), reached
    through a DIFFERENT cause than this test's unterminated quote -- both
    now deny, with the minimal fixed message and the close-defer escape."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, 'hq post --category handoff "unterminated', tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert 'omx close-defer --reason "<why>"' in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_missing_or_non_string_command_allows(tmp_path):
    mod = _load_handlers()
    assert mod.closure_guard({"tool_name": "Bash", "tool_input": {}, "cwd": str(tmp_path)}) is None
    assert mod.closure_guard({"tool_name": "Bash", "tool_input": {"command": 5},
                              "cwd": str(tmp_path)}) is None


# --- compound commands: split on && || ; | -----------------------------------

def test_compound_command_with_spaced_separator_is_seen(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "cd /tmp && hq post --category handoff", tmp_path)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_compound_command_with_glued_separator_is_seen(tmp_path):
    """wiring-facts §4: shlex glues a no-space separator into the adjacent
    token ('cd x&&hq' -> ['cd', 'x&&hq', 'post', ...]); the segment splitter
    must still see the closure declaration on the far side."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "cd /tmp&&hq post --category handoff", tmp_path)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_pipe_and_semicolon_compound_commands_are_seen(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    assert _run(mod, "true ; omx loop-disarm --reason done", tmp_path) is not None
    assert _run(mod, "true || omx loop-disarm --reason done", tmp_path) is not None


# --- F1 (task-5 fix-round-2): a real newline is a segment separator too -----

def test_newline_before_closure_command_denies(tmp_path):
    """team-lead's own repro: a literal newline (not `;`) is the ordinary
    shape of a multi-line Bash tool_input.command, and shlex.split treats it
    exactly like a space -- it produced no segment boundary before this fix,
    so a closure declaration on line 2 was invisible."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "echo starting\nhq post --category handoff", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_multiline_script_before_closure_command_denies(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "set -e\ncd .\nomx loop-mark-done --reason=done", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_closure_command_on_first_line_still_denies_control(tmp_path):
    """Control pinning WHERE the gap was: closure-first-then-newline always
    worked (the closure verb was already at the segment head); this is not a
    generic "newlines break shlex" story."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "hq post --category handoff\necho done", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_quoted_newline_in_summary_argument_does_not_trigger(tmp_path):
    """The quoted-argument property must survive the newline fix: this text
    is DATA (an argument), not a command, and must still allow."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, 'hq post --summary "see\n--category handoff"', tmp_path)
    assert out is None


# --- N1 (task-5 fix-round-4): an unquoted backslash-newline is a line
# CONTINUATION, not a separator -- the round-2 fix marked EVERY newline as a
# separator, which was right for an ordinary multi-line command but wrong for
# a continuation, which bash joins into ONE logical line.

def test_backslash_continuation_after_the_declaration_still_denies(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "hq post --category handoff \\\n  --summary x", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_backslash_continuation_inside_the_declaration_now_denies(tmp_path):
    """team-lead's own repro: the continuation splits `hq post` and
    `--category handoff` onto different physical lines -- round-2 marked
    that newline as a separator too, putting the verb and its own flag in
    different segments and silently allowing."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "hq post \\\n  --category handoff \\\n  --summary x", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_backslash_continuation_neighbor_shapes_still_deny(tmp_path):
    """The controller's own thirteen-shape sweep, the load-bearing subset:
    CRLF, tabs, an unrelated preceding continuation, chained continuations,
    and comment lines must all still see the declaration."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    for command in (
        "hq post --category handoff\r\n--summary x",
        "hq post\t\\\n--category handoff",
        "foo \\\nbar\nhq post --category handoff",
        "hq \\\npost \\\n--category handoff",
        "# comment\nhq post --category handoff",
        "hq post --category handoff\n# comment",
    ):
        out = _run(mod, command, tmp_path)
        assert out is not None, command
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", command


# --- N3 (task-5 fix-round-4): a heredoc BODY is data, not a command --------

def test_heredoc_body_containing_the_phrase_as_prose_allows(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod,
               "cat >> f <<'EOF'\nthe gate denies `hq post --category handoff` when ungraded\nEOF",
               tmp_path)
    assert out is None


def test_heredoc_body_that_is_literally_the_closure_command_allows(tmp_path):
    """team-lead's own repro: the false positive the round-3 re-review found
    -- a heredoc body line that reads exactly like the closure declaration
    (writing a runbook, a doc, a report) must not deny."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "cat > f <<'EOF'\nhq post --category handoff\nEOF", tmp_path)
    assert out is None


def test_heredoc_variants_all_allow(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    for command in (
        "cat > f <<EOF\nhq post --category handoff\nEOF",              # unquoted delimiter
        "cat > f <<-EOF\n\thq post --category handoff\nEOF",           # <<- strips leading tabs
        "cat > f <<'A'\nx\nA\ncat > g <<'B'\ny\nB",                     # two heredocs, no real command
        "python3 <<'PY'\nprint('hq post --category handoff')\nPY",     # text inside print()
    ):
        assert _run(mod, command, tmp_path) is None, command


def test_real_closure_command_after_a_closed_heredoc_still_denies(tmp_path):
    """The required negative twin: option (a) (track heredoc regions) must
    not blind the gate to a genuine closure command placed after a heredoc
    in the same command -- option (b) (stop marking after the first `<<`)
    would have silently missed exactly this."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "cat > f <<'EOF'\nsome text\nEOF\nhq post --category handoff", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- Ruling 30 (task-5 fix-round-5): a parse failure must never silently ---
# disable the gate for the rest of the command. All four are the same root
# cause: the round-4 heredoc tracker, once it entered a body region, had no
# way back out if the delimiter it extracted never matched anything later --
# swallowing the entire remainder of the command as inert "data" with no
# error, no signal, nothing in the suite. Each of the four commands below
# denies on 88a7bbb (pre-round-4) and allowed on the round-4 HEAD; each must
# deny again here. Exact strings from the review, not neighboring shapes.

def test_heredoc_opener_inside_a_comment_does_not_swallow_the_rest(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "# see <<EOF example\nhq post --category handoff", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_heredoc_opener_inside_a_comment_with_a_coincidental_later_match(tmp_path):
    """The exact repro above is ALSO rescued by Ruling 30's lookahead alone
    (the comment's embedded "EOF" delimiter never matches any later line in
    that string, so the pre-commitment check would discard it regardless of
    whether # is specially recognized) -- it does not, by itself, prove the
    comment fix has independent value. This one does: a real standalone
    "EOF" line genuinely exists later (an ordinary, if odd, bash shape --
    three statements: a comment, a real command, and a bare word). Without
    comment detection, the embedded "<<EOF" is still read as a heredoc
    opener, its delimiter now coincidentally matches that later line, and
    Ruling 30's OWN lookahead validates it as legitimate -- swallowing the
    real closure command as fake body. Recognizing the comment up front,
    before ever reaching `<<`, prevents this."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "# see <<EOF example\nhq post --category handoff\nEOF", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_here_string_is_not_a_heredoc(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, 'echo hi <<< "EOF"\nhq post --category handoff', tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_unquoted_here_string_word_does_not_open_a_phantom_heredoc(tmp_path):
    """The exact repro above is ALSO rescued by Ruling 30's lookahead alone
    (its mis-parsed "EOF" delimiter never matches anything in that string,
    so the pre-commitment check discards it regardless of whether <<< is
    specially recognized) -- it does not, by itself, prove the <<< fix has
    independent value. This one does: an unquoted here-string word "EOF"
    followed later by a real standalone "EOF" line is valid, ordinary bash
    (three separate statements on three lines -- a here-string has no body
    at all, so `hq post --category handoff` is genuinely its own command
    here) -- but the pre-round-5 double-processing bug extracts "EOF" as a
    phantom heredoc delimiter, and since a line "EOF" genuinely exists
    later, Ruling 30's OWN lookahead validates it as legitimate and
    swallows the real closure command as fake body. Only recognizing <<<
    up front (never attempting delimiter parsing for it at all) prevents
    this."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "echo hi <<< EOF\nhq post --category handoff\nEOF", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_backslash_in_delimiter_still_denies_the_command_after_the_heredoc(tmp_path):
    """Renamed and corrected (Task-11 cross-model round-1): this test's
    original name and framing ("never matches") described the round-5
    MECHANISM, not real bash semantics -- a mid-word backslash (`<<E\\OF`)
    quotes one character the same way `<<\\EOF` does (see
    test_backslash_quoted_heredoc_delimiter_strips_the_backslash above), and
    with backslash-stripping now correct, the delimiter DOES match "EOF"
    here. The verdict is unchanged (deny) but the REASON is now the correct
    one: the heredoc genuinely closes at the "EOF" line, swallowing only
    "body", and `hq post --category handoff` is a real, separate command
    AFTER the terminator -- not, as the old framing implied, an accidental
    deny from Ruling 30 giving up on an unmatchable delimiter."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "cat <<E\\OF\nbody\nEOF\nhq post --category handoff", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_unterminated_heredoc_does_not_swallow_the_rest_of_the_command(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "cat <<'EOF'\nbody never closed\nhq post --category handoff", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- comment conformance (fix-round-5): a `#` mid-word is not a comment ----

def test_hash_mid_word_is_not_a_comment(tmp_path):
    """bash's own rule: a `#` only starts a comment as the first character
    of a word. If 'a#b' or 'url#frag' were wrongly treated as comment
    starts, the real heredoc opener right after them on the same line would
    be swallowed as fake "comment" text -- meaning the closure command
    would surface as its own segment and (wrongly) deny. Correctly NOT
    treating them as comments lets the heredoc track normally and swallow
    the closure command as body data -- so the correct behavior here is
    ALLOW, and a comment-detection regression would flip this to deny."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    for prefix in ("echo a#b <<EOF", "echo url#frag <<EOF"):
        out = _run(mod, f"{prefix}\nhq post --category handoff\nEOF", tmp_path)
        assert out is None, prefix


def test_plain_comment_line_does_not_disable_the_gate(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "# plain comment\nhq post --category handoff", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_quoted_heredoc_marker_and_fd_prefixed_heredoc_controls(tmp_path):
    """Controls the re-review verified stay clean: `<<` inside a quoted
    string is not a heredoc opener; a plain redirect (`>`) is not one
    either; a fd-prefixed `2<<EOF` heredoc is still tracked and closed."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    assert _run(mod, 'echo "<<EOF"\nhq post --category handoff', tmp_path) is not None
    assert _run(mod, "echo redirect > /tmp/x\nhq post --category handoff", tmp_path) is not None
    assert _run(mod, "cat 2<<EOF\nbody\nEOF\nhq post --category handoff", tmp_path) is not None


# --- Task-11 cross-model findings, fresh loop round-1 (six defects, exact --
# strings verified by the controller against the code before dispatch) -----

def test_apostrophe_in_trailing_comment_denies_not_allows(tmp_path):
    """1.1, the worst finding of this round: an apostrophe in an ordinary
    bash comment ("# don't fail") corrupted this scan's own quote-tracking,
    made shlex.split raise on the marked string, and the outer fail-open
    turned that into a silent allow -- with no error anywhere. Ruling 37:
    dropping comment text at the source (rather than copying it through)
    removes the trigger; a residual shlex failure now denies regardless."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "hq post --category handoff # don't fail", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_apostrophe_in_leading_comment_denies_not_allows(tmp_path):
    """1.1b, same mechanism, comment on its own leading line."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "# Let's finish up\nhq post --category handoff", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_ansi_c_quoted_apostrophe_denies_not_allows(tmp_path):
    """1.2: not a comment at all -- this scan doesn't understand bash's
    $'...' ANSI-C quoting, mis-tracks the embedded escaped apostrophe as an
    unterminated single-quote span, and shlex.split correctly raises on the
    resulting marked string. Ruling 37 doesn't ask this scan to learn
    $'...' syntax -- only that the resulting parse failure denies instead
    of silently allowing (the second half of the ruling, independent of the
    comment-dropping fix, since no '#' is involved here at all)."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "echo $'don\\'t stop' ; hq post --category handoff", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_ampersand_background_operator_is_a_separator(tmp_path):
    """2.1/2.1b: `&` is a POSIX list separator (backgrounds the preceding
    command) and was simply absent from _CLOSURE_SEPARATORS -- both the
    spaced and glued-with-no-whitespace forms must be seen, the same
    distinction already proven for `&&`/`;`/`|` in earlier rounds."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    for command in ("sleep 1 & hq post --category handoff",
                     "sleep 1&hq post --category handoff"):
        out = _run(mod, command, tmp_path)
        assert out is not None, command
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", command


def test_and_and_is_still_recognized_after_adding_ampersand(tmp_path):
    """Negative twin for the `&` addition: `&&` must keep matching as ONE
    two-character operator, not as two separate `&` separators -- pins that
    _CLOSURE_SEP_RE's alternation order (`&&` before the bare `&`) is what
    it needs to be, not just that the tuple membership check happens to
    work out."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "cd /tmp && hq post --category handoff", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_backslash_quoted_heredoc_delimiter_strips_the_backslash(tmp_path):
    """3.1: `<<\\EOF` backslash-quotes ONE character of the delimiter word,
    the same way a backslash quotes anything else in unquoted bash -- the
    real terminator is "EOF", backslash removed. Treating the backslash as
    literal manufactured a delimiter that could never match, so a genuine
    heredoc whose body reads exactly like the closure declaration was
    scanned as a real command instead of swallowed as body data."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "cat <<\\EOF\nhq post --category handoff\nEOF\n", tmp_path)
    assert out is None


def test_crlf_heredoc_terminator_matches_with_cr_stripped(tmp_path):
    """3.2: a CRLF-terminated command left every candidate body/terminator
    line carrying a trailing \\r ("EOF\\r" != "EOF"), so a heredoc that
    should close normally looked unterminated to Ruling 30's lookahead and
    fell through to being scanned as commands."""
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "cat <<EOF\r\nhq post --category handoff\r\nEOF\r\n", tmp_path)
    assert out is None


# --- F4 (task-5 fix-round-2): a renderer failure must still deny -----------

def test_renderer_failure_still_denies_with_a_fallback_message(tmp_path, monkeypatch):
    """Once evaluate_completion has already decided incomplete/unreadable, a
    bug in the deny-TEXT renderer must not silently downgrade that decision
    into an allow (the reviewer's own demonstration: a malformed verdict
    missing the `missing`/`how` keys `_closure_incomplete_reason` needs).
    Patched on the real omx_core.completion module, since closure_guard's
    `from omx_core.completion import evaluate_completion` resolves against
    that same module object on every call."""
    import omx_core.completion as completion_mod
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")

    bad_verdict = {"state": "incomplete", "missing": [{"run": "runs/alpha"}]}  # no "missing"/"how" per entry
    monkeypatch.setattr(completion_mod, "evaluate_completion", lambda paths: bad_verdict)

    out = _run(mod, "omx loop-disarm --reason done", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "omx close-check" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert 'omx close-defer --reason "<why>"' in out["hookSpecificOutput"]["permissionDecisionReason"]


# --- unreadable / no-contract / checked states -------------------------------

def test_unreadable_denies(tmp_path):
    mod = _load_handlers()
    _setup_unreadable(tmp_path)
    out = _run(mod, "omx loop-disarm --reason done", tmp_path)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "not-a-dir" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_missing_output_root_now_allows_a_closure_command(tmp_path):
    """Ruling 29 (task-5 fix-round-2): a project that bootstrapped a
    contract but has not produced any training output at all -- output_root
    literally never created -- is the ordinary shape of a project between
    declaring a contract and finishing its first run, and must not lock an
    operator out of closing a completely unrelated session. Negative twin of
    test_unreadable_denies above: same "cannot list" family of causes,
    opposite existence, opposite verdict."""
    mod = _load_handlers()
    _setup(tmp_path, output_root="never-created")
    assert _run(mod, "omx loop-disarm --reason done", tmp_path) is None


def test_no_contract_allows(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path, run_completion=None)
    assert _run(mod, "omx loop-disarm --reason done", tmp_path) is None


def test_checked_clean_tree_allows(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    run_dir = tmp_path / "experiments" / "runs" / "alpha"
    _finish(run_dir)
    _satisfy_required(run_dir)
    assert _run(mod, "omx loop-disarm --reason done", tmp_path) is None


def test_checked_zero_runs_allows(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    (tmp_path / "experiments").mkdir()
    assert _run(mod, "omx loop-disarm --reason done", tmp_path) is None


# --- success criterion 3: an unanchored cwd never speaks ---------------------

def test_unanchored_cwd_with_no_omx_layer_at_all_allows(tmp_path):
    """Negative twin of the test below (Ruling 27, fix-round-1): no
    .omx-workspace marker, no git repo, and -- the fact that actually
    matters -- no `.omx/` or `.hq/` layer either. The #13 ladder falls back
    to stage 'cwd' and `_has_omx_marker(cwd)` is also False, so the handler
    must short-circuit BEFORE touching the filesystem: this is the
    Finding-8-class regression (a Bash-matched gate denying in every
    unrelated repo on the machine) the round exists to close."""
    mod = _load_handlers()
    out = mod.closure_guard(_payload("omx loop-disarm --reason done", tmp_path))
    assert out is None


def test_unanchored_but_bootstrapped_project_now_denies(tmp_path):
    """Fix-round-1, Ruling 27 -- corrects a defect this round shipped once:
    a directory that is a REAL omx project (bootstrapped profile, declared
    contract, a genuinely incomplete finished run) but sits outside git and
    without a `.omx-workspace` marker used to allow every closure command,
    because the #13 ladder's stage=='cwd' was wrongly treated as "no omx
    project here" -- the ladder never checks for `.omx/`/`.hq/` at all, so
    that conflated "ladder found no anchor" with "no project exists".
    `_closure_resolve_root` now falls back to `_has_omx_marker(cwd)` when the
    ladder itself doesn't anchor, and gates against cwd when it finds a real
    omx layer there. This is the twin of the allow test above: same
    ladder outcome (stage 'cwd'), opposite omx-layer presence, opposite
    verdict."""
    mod = _load_handlers()
    _setup(tmp_path, anchor=False)  # bootstrapped profile, but no marker/git
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "omx loop-disarm --reason done", tmp_path)
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- defer / receipt rescue, verified both ways (revert experiment) ---------

def test_without_any_rescue_the_incomplete_tree_denies(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "omx loop-disarm --reason done", tmp_path)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_active_defer_rescues_an_incomplete_tree(tmp_path):
    mod = _load_handlers()
    paths = _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    write_defer(paths, "waiting on hardware", now_iso())
    assert _run(mod, "omx loop-disarm --reason done", tmp_path) is None


def test_stale_defer_does_not_rescue(tmp_path):
    mod = _load_handlers()
    paths = _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    old = (parse_iso_utc(now_iso(), "now") - timedelta(hours=13)).isoformat()
    write_defer(paths, "waiting on hardware", old)
    out = _run(mod, "omx loop-disarm --reason done", tmp_path)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_defer_missing_reason_does_not_rescue(tmp_path):
    """active_defer (Ruling 26) requires a readable, non-empty reason -- a
    hand-edited defer without one must not be treated as a recorded escape."""
    mod = _load_handlers()
    paths = _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    defer_path = (paths.omx_dir / "completion-defer.json")
    defer_path.parent.mkdir(parents=True, exist_ok=True)
    defer_path.write_text(json.dumps({"deferred_at": now_iso()}))  # no "reason"
    out = _run(mod, "omx loop-disarm --reason done", tmp_path)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_fresh_local_receipt_rescues(tmp_path):
    mod = _load_handlers()
    paths = _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    write_receipt(paths, {"state": "checked", "runs": []}, source="local", now_iso=now_iso())
    assert _run(mod, "omx loop-disarm --reason done", tmp_path) is None


def test_stale_local_receipt_does_not_rescue(tmp_path):
    mod = _load_handlers()
    paths = _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    old = (parse_iso_utc(now_iso(), "now") - timedelta(hours=13)).isoformat()
    write_receipt(paths, {"state": "checked", "runs": []}, source="local", now_iso=old)
    out = _run(mod, "omx loop-disarm --reason done", tmp_path)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_receipt_copied_from_another_root_does_not_rescue(tmp_path):
    mod = _load_handlers()
    paths = _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    write_receipt(paths, {"state": "checked", "runs": []}, source="local", now_iso=now_iso())
    receipt_path = paths.omx_dir / "completion-receipt.json"
    data = json.loads(receipt_path.read_text())
    data["root"] = "/some/other/project"
    receipt_path.write_text(json.dumps(data))
    out = _run(mod, "omx loop-disarm --reason done", tmp_path)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_remote_receipt_rescues_an_unreadable_tree(tmp_path):
    mod = _load_handlers()
    paths = _setup_unreadable(tmp_path)  # unreadable locally
    write_receipt(paths, {"state": "checked", "runs": []}, source="remote", now_iso=now_iso(),
                  origin_root="/container/project")
    assert _run(mod, "omx loop-disarm --reason done", tmp_path) is None


# --- import-safety: a poisoned omx_core still allows -------------------------

def test_poisoned_omx_core_import_still_allows(tmp_path, monkeypatch):
    mod = _load_handlers()
    for name in ("omx_core", "omx_core.clock", "omx_core.completion", "omx_core.omx_paths"):
        monkeypatch.setitem(sys.modules, name, None)
    out = mod.closure_guard(_payload("omx loop-disarm --reason done", tmp_path))
    assert out is None


# --- deny reason shape --------------------------------------------------------

def test_incomplete_deny_reason_names_run_missing_how_and_escape(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    out = _run(mod, "omx loop-disarm --reason done", tmp_path)
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "runs/alpha" in reason
    assert "eval/*.json" in reason
    assert "python analysis/eval.py static --run runs/alpha" in reason
    assert 'omx close-defer --reason "<why>"' in reason
    assert len(reason) <= 1200


def test_deny_reason_never_advertises_the_skip_hook_bypass(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    incomplete = _run(mod, "omx loop-disarm --reason done", tmp_path)
    assert "OMX_SKIP_HOOKS" not in incomplete["hookSpecificOutput"]["permissionDecisionReason"]

    _setup_unreadable(tmp_path / "other")
    unreadable = _run(mod, "omx loop-disarm --reason done", tmp_path / "other")
    assert "OMX_SKIP_HOOKS" not in unreadable["hookSpecificOutput"]["permissionDecisionReason"]


def test_incomplete_deny_reason_shares_one_how_line_when_many_runs_match(tmp_path):
    """Pin the length ceiling under adversarial width: many finished-but-
    incomplete runs, with a `how` template that has no `{run}` placeholder
    (so the SUBSTITUTED text -- what actually gets compared -- is literally
    identical across every run, not merely the same template before
    substitution). Assembly must fold to one shared 'make it' line plus a
    '+N more' line, not N repeats."""
    mod = _load_handlers()
    shared_how_contract = dict(CONTRACT, how="python analysis/eval.py static --all")
    _setup(tmp_path, run_completion=shared_how_contract)
    for i in range(10):
        _finish(tmp_path / "experiments" / "runs" / f"run{i}")
    out = _run(mod, "omx loop-disarm --reason done", tmp_path)
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert len(reason) <= 1200
    assert "+7 more" in reason  # 10 runs total, 3 shown
    assert reason.count("make it:") == 1  # shared how printed once, not per-run


def test_unreadable_deny_reason_names_reason_and_escape_commands(tmp_path):
    mod = _load_handlers()
    _setup_unreadable(tmp_path)
    out = _run(mod, "omx loop-disarm --reason done", tmp_path)
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "not-a-dir" in reason
    assert "omx close-check --root" in reason
    assert "omx close-ack --from -" in reason
    assert 'omx close-defer --reason "<why>"' in reason
    assert len(reason) <= 1200


def test_unreadable_from_malformed_contract_names_the_key_reason(tmp_path):
    mod = _load_handlers()
    _setup(tmp_path, run_completion={"runs": 123})  # missing required keys
    out = _run(mod, "omx loop-disarm --reason done", tmp_path)
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "run_completion" in reason


# --- end to end through the real dispatcher (dispatcher-shaped exercise) ----

def test_end_to_end_through_runner_denies(tmp_path):
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    payload = _payload("omx loop-disarm --reason done", tmp_path)
    r = subprocess.run([sys.executable, str(RUNNER), "closure_guard"],
                       input=json.dumps(payload), capture_output=True, text=True,
                       timeout=10, env={**os.environ})
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_end_to_end_through_runner_allows_non_closure_command(tmp_path):
    _setup(tmp_path)
    _finish(tmp_path / "experiments" / "runs" / "alpha")
    payload = _payload("ls -la", tmp_path)
    r = subprocess.run([sys.executable, str(RUNNER), "closure_guard"],
                       input=json.dumps(payload), capture_output=True, text=True,
                       timeout=10, env={**os.environ})
    assert r.returncode == 0
    assert r.stdout.strip() == ""  # allow prints nothing at all


def test_plugin_json_registers_closure_guard_on_bash():
    manifest = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())
    bash_entries = [e for e in manifest["hooks"]["PreToolUse"] if e.get("matcher") == "Bash"]
    assert len(bash_entries) == 1
    args = bash_entries[0]["hooks"][0]["args"]
    assert args[1] == "closure_guard"
    # the existing Edit|Write entry (report_guard) must be untouched, not widened
    edit_write = [e for e in manifest["hooks"]["PreToolUse"] if e.get("matcher") == "Edit|Write"]
    assert len(edit_write) == 1
    assert edit_write[0]["hooks"][0]["args"][1] == "report_guard"
