"""omx hook handlers — pure functions (stdin dict -> decision dict | None).

report_guard (spec 3.2): deny Edit/Write on gated exp-analyze deliverables
(analysis/<analysis_id>/{report.md, report.ko.md, manifest.json}). The
legitimate write path is Bash -> omx_core atomic_path (exp-analyze's writer),
which a PreToolUse Edit|Write matcher never sees — so the guard cannot fire on
a gate-passing write. Closes the 0.1.14 hand-Edit incident at edit time; the
intentional friction on one-character fixes is accepted (that WAS the incident).
Fail-open: unparseable input or an unavailable omx_core -> allow (None).
"""
import re
from pathlib import PurePosixPath

_GATED_NAMES = frozenset({"report.md", "report.ko.md", "manifest.json"})

# Local mirror of omx_paths._ANALYSIS_ID; refreshed from omx_core when importable.
_TS = r"\d{8}-\d{6}"
_ANALYSIS_ID = re.compile(rf"\A(?:[a-z][a-z0-9]*-{_TS}|{_TS}-[a-z][a-z0-9]*)\Z")
try:  # prefer the core's regex so the two can never drift silently
    from omx_core.omx_paths import _ANALYSIS_ID as _CORE_ANALYSIS_ID
    _ANALYSIS_ID = _CORE_ANALYSIS_ID
except Exception:
    pass  # stdlib fallback keeps the guard alive without an installed core

_DENY_REASON = (
    "omx report-guard: gated deliverables (analysis/<id>/report.md, report.ko.md, "
    "manifest.json) are written only by the exp-analyze atomic_path writer — "
    "re-enter the exp-analyze skill (RE-analysis) with the old report as BASE "
    "instead of hand-editing; report-coverage will re-stamp it. "
    "Escape hatch (explicit, logged intent): OMX_SKIP_HOOKS=report_guard."
)


def report_guard(payload):
    if payload.get("tool_name") not in ("Edit", "Write"):
        return None
    file_path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not file_path:
        return None
    p = PurePosixPath(file_path.replace("\\", "/"))
    if p.name not in _GATED_NAMES:
        return None
    parts = p.parts
    if len(parts) < 3:
        return None
    if not _ANALYSIS_ID.fullmatch(parts[-2]) or parts[-3] != "analysis":
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": _DENY_REASON,
    }}


# --- route_emit (spec 2.1): experiment-work STAGE checkpoint -----------------
# Static, stdlib-only, omd route_emit.py MVP pattern: the hook only names the
# stage vocabulary and the routing non-negotiables; procedure bodies live in
# skills/*/SKILL.md so there is nothing here to drift. Size-capped by test
# (<= 2 KiB) because this is paid on every prompt.
_ROUTE_CHECKPOINT = (
    "<omx-routing>\n"
    "실험 분석·설계 작업(훈련 런 분석, 다음 실험 설계, 반자율 루프, 실험 지식/트리 관리)이면,\n"
    "행동 전에 한 줄로 판정하라:\n"
    "- 단계: exp-init(프로파일 부트스트랩) / exp-analyze(런 분석→report) / "
    "exp-design(다음 실험 proposal) / exp-loop(반자율 analyze→design→eval 루프) / "
    "wiki(실험 지식 add·query·gc) / tree(출력 트리 codify·audit·scaffold) / "
    "recipe(진단 절차 승격·소비).\n"
    "단일 단계면 그 스킬/verb 직접, 반복 사이클이면 exp-loop.\n"
    "⚠️ 훈련 launch는 절대 자동 실행 금지 — `omx queue-launch`로 큐만 (사람 승인 게이트).\n"
    "⚠️ report.md는 hand-parse 금지 — `omx report-parse` 경유.\n"
    "⚠️ 결과 SSOT는 experiments 트리 — 결과를 다른 곳에 쓰지 말 것.\n"
    "⚠️ 지식 SSOT 우선(분석·설계·판단 전 필독): 진단 임계값·이전 원인·컨벤션 등 "
    "'워크스페이스가 이미 아는 것'은 소스·일반 관행·내 기억보다 먼저 omx wiki를 SSOT로 "
    "query하라(`omx wiki query --root <root>`; exp-analyze/exp-design엔 이미 강제, "
    "손으로 쓸 때도 동일). wiki에 답이 있는데 추측으로 때우는 것은 결함이다.\n"
    "⚠️ 백로그 전파(요약/plan 작성 전 필수): README·report·DESIGN·plan의 'next steps/"
    "미해결/delta' 섹션을 쓰기 전 `omx wiki list --status`로 열거·대조하라 — 모든 open "
    "lead는 실리거나 사유와 함께 명시적 defer; 열린 blocking(needs-apply-before-retrain)은 "
    "delta 목록 또는 launch ack에 반드시 명시. 조용한 탈락은 결함이다.\n\n"
    "실험 작업이면, 판정을 응답 맨 앞 omha ROUTE 줄 바로 다음에 이 한 줄로 출력하라(누락 금지):\n"
    "STAGE(exp) → <exp-init|exp-analyze|exp-design|exp-loop|wiki|tree|recipe> · <한 줄 근거>\n"
    "실험 작업이 아니면 이 블록 전체 무시(STAGE 줄도 출력하지 말 것).\n"
    "</omx-routing>"
)


def _fetch_open_backlog(payload):
    """Pre-fetch the LIVE open actionable backlog and format it as an unmissable
    injected block. Turns the advisory 'go run omx wiki list' pointer into
    in-context DATA, so a next-experiment / next-steps decision physically cannot
    skip an open lead (the stranded-instruction incident 2026-07-15).

    Fail-open (D9): ANY error -> '' (no injection). This runs on every prompt, so
    a broken fetch must degrade to nothing, never break the route hook.
    """
    try:
        import json
        import subprocess

        root = _omx_root(payload)  # raises if the payload cwd is not an omx project
        lines = []
        for st in ("needs-experiment", "needs-apply-before-retrain"):
            proc = subprocess.run(
                ["omx", "wiki", "list", "--status", st, "--root", root],
                capture_output=True, text=True, timeout=4,
            )
            if proc.returncode != 0:
                continue
            for page in json.loads(proc.stdout).get("pages", [])[:20]:
                blocked = page.get("blocked_on") or "unblocked"
                lines.append(f"  [{st}] {page.get('slug', '?')} (blocked: {blocked})")
        if not lines:
            return ""
        return (
            "<omx-open-backlog>\n"
            "LIVE actionable leads on THIS omx root (auto-fetched every turn). Before "
            "choosing a next experiment/direction OR writing any next-steps / 미해결 / "
            "delta section, reconcile against EVERY line below — carry it or defer it "
            "with a stated reason. Silent omission is a defect.\n"
            + "\n".join(lines)
            + "\n</omx-open-backlog>"
        )
    except Exception:
        return ""  # fail-open: never break the per-prompt route hook


def route_emit(payload):
    ctx = _ROUTE_CHECKPOINT
    backlog = _fetch_open_backlog(payload)
    if backlog:
        ctx = ctx + "\n\n" + backlog
    return {"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": ctx,
    }}


# --- shared root resolution for omx_core-backed handlers ---------------------
def _omx_root(payload) -> str:
    """Resolve the .omx anchor from the hook payload's cwd via the #13 ladder.
    Raises on failure — callers are fail-open and treat any raise as 'allow'."""
    from omx_core.root import resolve_omx_root
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        raise ValueError("hook payload carries no usable cwd")
    root, _source = resolve_omx_root(cwd=cwd)
    return str(root)


# --- capture_flush (spec 2.2): SessionEnd rescue --------------------------------
def capture_flush(payload):
    """Flush the produced-reports ledger into session-log wiki stubs.

    Returns None ALWAYS: the platform ignores SessionEnd hook output entirely
    (side effects only), so the flush's whole effect is the file-side capture.
    Fail-open: no omx_core / no root / any error -> None, nothing written."""
    try:
        from omx_core import clock
        from omx_core.omx_paths import OmxPaths
        from omx_core.wiki.capture import flush_produced_reports

        # naive-UTC now: capture writes wiki pages (the wiki's clock contract).
        now = clock.now_iso_naive()
        flush_produced_reports(OmxPaths(root=_omx_root(payload)), now=now)
    except Exception:
        pass  # fail-open (D9): a broken flush degrades to no capture
    return None


# --- compact_breadcrumb (spec 2.3): post-compaction durable-state pointer ----
# Registered SessionStart matcher "compact" (PreCompact carries no
# additionalContext channel — docs v2.1.202). READ-ONLY per D-R3-6: the skills
# write the breadcrumbs; this handler only points the fresh context at them.
_NOTES_FRESH_S = 48 * 3600


def compact_breadcrumb(payload):
    try:
        if payload.get("source") != "compact":
            return None
        import time

        from omx_core.omx_paths import OmxPaths
        from omx_core.state import load_state

        paths = OmxPaths(root=_omx_root(payload))
        omx = paths.omx_dir
        lines = []
        try:
            cutoff = time.time() - _NOTES_FRESH_S
            fresh = [str(p) for p in sorted(omx.glob("scratch/*/notes.md"))
                     if p.stat().st_mtime >= cutoff]
            if fresh:
                lines.append("scratch notes (analysis breadcrumb trail): "
                             + ", ".join(fresh))
        except OSError:
            pass
        try:
            env = load_state(paths).get("active_loop")
            if env:
                lines.append(
                    f"armed exp-loop: run {env.get('run_id')} iteration "
                    f"{env.get('iteration')} deadline {env.get('deadline')}")
        except Exception:
            pass
        try:
            queued = sorted(p.parent.name for p in omx.glob("runs/*/pending-launch.json"))
            if queued:
                lines.append("pending launches awaiting HUMAN approval: "
                             + ", ".join(queued))
        except OSError:
            pass
        if not lines:
            return None  # silence over noise
        body = (
            "<omx-durable-state> this session was just compacted — re-read: "
            + " | ".join(lines)
            + " — scratch notes are the analysis breadcrumb trail; pending "
              "launches require the human gate; an armed loop is resumed only "
              "per exp-loop SKILL. </omx-durable-state>")
        return {"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": body,
        }}
    except Exception:
        return None  # fail-open (D9)


# --- loop_gate (spec 2.4): thin Stop gate for exp-loop persistent mode -------
# D-R3-1: a dumb gate. It reads {armed, deadline, iteration, hard_cap,
# adopted_session}, blocks with a FROZEN continuation prompt, and never makes
# an analyze/design/eval decision — those live in skills/exp-loop/SKILL.md.
# stop_hook_active is deliberately not consulted: repeated blocks across turns
# ARE the loop; runaway is bounded by the mandatory deadline and hard_cap.
_LOOP_CONTINUATION = (
    "omx exp-loop iteration {iteration} (run {run_id}): continue the cycle per "
    "skills/exp-loop/SKILL.md — analyze -> design -> eval -> decide -> log. "
    "Queue any training launch with `omx queue-launch` for human approval; "
    "NEVER execute a training launch yourself (D4). When the deadline passes "
    "or the work is done, run `omx loop-disarm --reason done`."
)


def loop_gate(payload):
    try:
        from omx_core import clock
        from omx_core.lock import release_run_lease, with_file_lock
        from omx_core.loop import deadline_passed, mark_loop_done
        from omx_core.omx_paths import OmxPaths
        from omx_core.state import load_state, save_state

        paths = OmxPaths(root=_omx_root(payload))

        def _crit():
            state = load_state(paths)
            env = state.get("active_loop")
            if not env:
                return None

            def _disarm_inline(reason):
                # Inline disarm while ALREADY holding the state lock. We must NOT
                # call the public lock-wrapped disarm_loop here: fcntl locks are
                # non-reentrant across fds in one process, so disarm_loop's own
                # flock(LOCK_EX) on a second fd of the same lock file would block
                # until with_file_lock times out and the gate fail-opens. So do
                # the disarm's side effects (marker + lease release) inline.
                rid = env.get("run_id")
                if rid:
                    now2 = clock.now_iso()
                    mark_loop_done(paths, rid, reason=reason,
                                   summary=f"iteration {env.get('iteration')}",
                                   now_iso=now2)
                    release_run_lease(paths, rid)
                state["active_loop"] = None
                save_state(paths, state)
                return None

            now = clock.now_iso()
            if deadline_passed(env["deadline"], now):
                return _disarm_inline("deadline")
            if env.get("iteration", 0) >= env.get("hard_cap", 50):
                return _disarm_inline("hard_cap")
            # circuit backstop (D-R4-4): best-effort — a circuit-evaluation error
            # (including a missing ledger) skips the branch (fail-open), so a
            # ledger-read failure disables the backstop by design. The verb +
            # exp-loop step 4.5 is the AUTHORITATIVE stop; this is the backstop.
            # NOTE: this runs BEFORE the session-adoption check by design —
            # plateau/fault are objective ledger-derived facts (like deadline/
            # hard_cap), and every self-disarm branch intentionally runs from any
            # session (R3 crash-recovery precedent), so the backstop is allowed to
            # disarm regardless of which session owns the loop.
            from omx_core.loop import (FAULT_STREAK_DEFAULT,
                                       PLATEAU_DISCARDS_DEFAULT, loop_health)
            plateau_discards = PLATEAU_DISCARDS_DEFAULT
            fault_streak = FAULT_STREAK_DEFAULT
            try:
                from omx_core.profile import load_profile_metrics
                prof = load_profile_metrics(paths.root)
                plateau_discards = int(prof.get("plateau_discards", plateau_discards))
                fault_streak = int(prof.get("fault_streak", fault_streak))
            except Exception:
                pass  # no profile yet -> named-constant defaults (D12: override slot)

            def _tripped(health):
                if health["consecutive_discards"] >= plateau_discards:
                    return "plateau"
                if health["consecutive_faults"] >= fault_streak:
                    return "fault_circuit"
                return None

            # D-R5-6: narrow the exception handling. ABSENT ledger -> skip silently
            # (normal before the first record). CORRUPT ledger -> count it toward a
            # bounded stop, but FIRST consult the last-healthy mirror (corruption
            # cannot rewind it). Any OTHER exception keeps today's blanket fail-open.
            from omx_core.ledger import (LedgerCorruptError, read_run_ledger)
            try:
                health = loop_health(read_run_ledger(paths, env["run_id"]),
                                     plateau_discards=plateau_discards,
                                     fault_streak=fault_streak)
                # healthy read: reset the corrupt-probe counter (persist — a stale
                # count must not survive a healthy probe).
                if env.get("ledger_probe_failures"):
                    env["ledger_probe_failures"] = 0
                    state["active_loop"] = env
                    save_state(paths, state)
                reason = _tripped(health)
                if reason:
                    return _disarm_inline(reason)
            except LedgerCorruptError:
                # mirror consult first: a mirrored streak trips the usual reason.
                mirror = env.get("health_mirror")
                if mirror:
                    reason = _tripped(mirror)
                    if reason:
                        return _disarm_inline(reason)
                # else: count the corrupt probe, PERSIST it, and stop at 3.
                env["ledger_probe_failures"] = env.get("ledger_probe_failures", 0) + 1
                state["active_loop"] = env
                save_state(paths, state)
                if env["ledger_probe_failures"] >= 3:
                    return _disarm_inline("ledger_corrupt")
            except Exception:
                pass  # blanket fail-open for any non-corrupt failure (D9 untouched)
            sid = payload.get("session_id")
            adopted = env.get("adopted_session")
            if adopted and sid and adopted != sid:
                return None  # another session's loop — pass through untouched
            if not adopted and sid:
                env["adopted_session"] = sid  # first blocked session owns the loop
            env["iteration"] = env.get("iteration", 0) + 1
            state["active_loop"] = env
            save_state(paths, state)
            return {"decision": "block",
                    "reason": _LOOP_CONTINUATION.format(
                        iteration=env["iteration"], run_id=env["run_id"])}

        return with_file_lock(paths.state_lock(), _crit)
    except Exception:
        return None  # fail-open (D9): a broken gate must never trap a session


HANDLERS = {
    "report_guard": report_guard,
    "route_emit": route_emit,
    "capture_flush": capture_flush,
    "compact_breadcrumb": compact_breadcrumb,
    "loop_gate": loop_gate,
}
