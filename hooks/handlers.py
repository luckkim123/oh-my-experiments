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
from pathlib import Path, PurePosixPath

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
    "program(다단계 실험 라인 계획) / "
    "wiki(실험 지식 add·query·gc) / tree(출력 트리 codify·audit·scaffold) / "
    "recipe(진단 절차 승격·소비).\n"
    "단일 단계면 그 스킬/verb 직접, 반복 사이클이면 exp-loop.\n"
    "⚠️ 실험 계획은 `.sp/plans/` 금지 — 단발 probe=exp-design proposal, 다단계 라인="
    "`.hq/community/programs/<id>/PLAN.md`(구 `.omx/programs/…`)"
    "(`omx program-init`, 캠페인 없이 열림).\n"
    "⚠️ 훈련 launch는 절대 자동 실행 금지 — `omx queue-launch`로 큐만 (사람 승인 게이트).\n"
    "⚠️ report.md는 hand-parse 금지 — `omx report-parse` 경유.\n"
    "⚠️ 결과 SSOT는 experiments 트리 — 결과를 다른 곳에 쓰지 말 것.\n"
    "⚠️ 지식 SSOT 우선(판단 전 필독): 진단 임계값·이전 원인·컨벤션은 내 기억보다 먼저 "
    "`omx wiki query --root <root>`. 답이 wiki에 있는데 추측은 결함이다.\n"
    "⚠️ 백로그 전파(요약/plan 작성 전 필수): README·report·DESIGN·plan의 'next steps/"
    "미해결/delta' 섹션을 쓰기 전 `omx wiki list --status needs-experiment`와 "
    "`--status needs-apply-before-retrain`으로 열거·대조하라 — 모든 open "
    "lead는 실리거나 사유와 함께 명시적 defer; 열린 blocking(needs-apply-before-retrain)은 "
    "delta 목록 또는 launch ack에 반드시 명시. 조용한 탈락은 결함이다.\n\n"
    "실험 작업이면, 판정을 응답 맨 앞 omha ROUTE 줄 바로 다음에 이 한 줄로 출력하라(누락 금지):\n"
    "STAGE(exp) → <exp-init|exp-analyze|exp-design|exp-loop|program|wiki|tree|recipe> · "
    "<한 줄 근거>\n"
    "실험 작업이 아니면 이 블록 전체 무시(STAGE 줄도 출력하지 말 것).\n"
    "</omx-routing>"
)


# Timeout for the backlog pre-fetch. ONE unfiltered `omx wiki list` call
# (filtered locally by status) must fit inside run_hook.py's default 3s SIGALRM
# budget for route_emit (1.2s < 3s); pinned by test_hook_backlog.py. The cost is
# startup-bound (~0.4s wall), not corpus-bound (parsing 253 pages is ~3ms).
# The campaign-drift check (_fetch_campaign_drift) is in-process file I/O, no
# subprocess — it shares this same 3s SIGALRM budget without its own timeout.
_BACKLOG_FETCH_TIMEOUT_S = 1.2

#: Injection order: soft leads first, blocking gates last (closest to the ack).
_OPEN_STATUSES = ("needs-experiment", "needs-apply-before-retrain")


def _resolve_backlog_root(payload) -> str:
    """Resolve the anchor for the backlog pre-fetch / campaign-drift check
    ONLY (omx-2 fix). NOT used by closure_guard (task 5, fix-round-1,
    Ruling 27) -- that gate needs a ladder "no anchor" result to fall back to
    an omx-LAYER check (`_has_omx_marker`) before giving up, which this
    function deliberately does not do; see `_closure_resolve_root`'s
    docstring for why that lives separately instead of being folded in here.
    Raises when the payload cwd is missing/empty OR when the #13 ladder never
    anchors (stage == "cwd") — resolve_omx_root itself never raises (root.py:36
    always falls back at least to cwd), so THIS caller treats that weakest
    fallback as "no omx root" and short-circuits before shelling out `omx wiki
    list` against a bogus root. _omx_root (shared by the other handlers) stays
    lenient on purpose — see its docstring."""
    from omx_core.root import resolve_omx_root
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        raise ValueError("hook payload carries no usable cwd")
    root, stage = resolve_omx_root(cwd=cwd)
    if stage == "cwd":
        raise ValueError(f"no omx root anchor found for cwd {cwd!r}")
    return str(root)


def _fetch_open_backlog(payload):
    """Pre-fetch the LIVE open actionable backlog and format it as an unmissable
    injected block. Turns the advisory 'go run omx wiki list' pointer into
    in-context DATA, so a next-experiment / next-steps decision physically cannot
    skip an open lead (the stranded-instruction incident 2026-07-15).

    Two-tier degradation (narrowed from blanket D9 fail-open, 2026-07-16 audit):
    - no omx root -> '' (silent; route_emit fires in every project, non-omx cwds
      are the normal case, silence is correct);
    - a FAILED fetch on a REAL omx root (nonzero exit, timeout, unparseable
      stdout) -> a visible WARN block naming the manual fallback command. The
      old ANY-error->'' path silently erased the backlog on any stray stdout
      line (deprecation notice, cache-vs-repo output-shape skew), re-arming the
      exact incident this fetch exists to prevent. Never raises either way.
    """
    try:
        import json
        import subprocess

        try:
            root = _resolve_backlog_root(payload)
        except Exception:
            return ""  # not an omx project — silence is correct
        try:
            proc = subprocess.run(
                ["omx", "wiki", "list", "--root", root],
                capture_output=True, text=True, timeout=_BACKLOG_FETCH_TIMEOUT_S,
            )
            # rc 2 is `wiki list`'s "the post store is unreadable" — it still
            # prints the full catalog, and the store-unreadable branch below says
            # more than the generic FAILED text this would otherwise fall into.
            if proc.returncode not in (0, 2):
                raise RuntimeError(f"omx wiki list exited {proc.returncode}")
            _out = json.loads(proc.stdout)
            pages = _out.get("pages", [])
            # Absent on an omx older than the post-store union — treat that as
            # readable, since there was no second source to fail.
            _ps = _out.get("post_store") or {"ok": True, "error": None}
            store_ok = _ps.get("ok") is not False
            store_err = _ps.get("error")
            if not isinstance(pages, list):
                # valid JSON but wrong shape must degrade VISIBLY too, not fall
                # through to the silent outer catch during formatting.
                raise RuntimeError("unexpected wiki-list output shape")
        except Exception as exc:
            return (
                "<omx-open-backlog>\n"
                f"WARN: open-backlog pre-fetch FAILED ({type(exc).__name__}) — open "
                "leads may exist but could not be injected this turn. Before any "
                "next-steps / plan / launch decision, enumerate them manually: "
                "`omx wiki list --status needs-experiment` and "
                "`--status needs-apply-before-retrain`.\n"
                "</omx-open-backlog>"
            )
        lines = []
        for st in _OPEN_STATUSES:
            for page in [p for p in pages if p.get("status") == st][:20]:
                blocked = page.get("blocked_on") or "unblocked"
                lines.append(f"  [{st}] {page.get('slug', '?')} (blocked: {blocked})")
        if not lines:
            if not store_ok:
                # Silence here would be the original defect in a new place: the
                # store that HOLDS the open leads was unreachable, and a zero from
                # an unread source is not a zero.
                return (
                    "<omx-open-backlog>\n"
                    f"WARN: the post store could not be read ({store_err}) — open "
                    "leads live there since the wiki→posts conversion, so this turn "
                    "saw only the legacy wiki dir. Enumerate manually before any "
                    "next-steps / plan / launch decision: "
                    "`hq query --status needs-experiment` and "
                    "`--status needs-apply-before-retrain`.\n"
                    "</omx-open-backlog>"
                )
            if not pages:
                return ""   # store readable and genuinely empty — nothing to say
            # An empty backlog is ALSO what a wiki whose writers never set
            # --status looks like, and the zero alone cannot tell the two apart.
            # Measured on one workspace 2026-08-10: 540 pages, 0 blocking,
            # 459 with no status at all — the launch gate had never had anything
            # to refuse, and a plan author had to hand-write a section titled
            # "why the machine backlog reads empty" to say so. State the
            # coverage so the zero can be read instead of trusted.
            unstatused = sum(1 for p in pages if not p.get("status"))
            return (
                "<omx-open-backlog>\n"
                f"0 open leads. Coverage: {unstatused}/{len(pages)} pages carry NO status — "
                "an empty backlog is not evidence that nothing is open, it is also what a "
                "wiki nobody files against looks like. Do not report 'no blockers' from this "
                "zero alone; check what this round's own findings should have filed "
                "(`omx wiki add --status`).\n"
                "</omx-open-backlog>"
            )
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
        return ""  # last-resort fail-open: never break the per-prompt route hook


def _fetch_campaign_drift(payload):
    """Conditional campaign-drift block (v0.8.0): empty string unless drift
    exists — the zero-tax-when-healthy pattern (cf. oms scholar_resume_emit).
    In-process lazy import, pure file I/O (no subprocess); ANY failure —
    omx_core absent (poison-import contract), no root anchor, no tree.yaml,
    yaml missing, schema error — fails open to ""."""
    try:
        root = _resolve_backlog_root(payload)
    except Exception:
        return ""
    try:
        from omx_core.campaign import campaign_drift
        from omx_core.omx_paths import OmxPaths
        from omx_core.tree import load_tree_schema
        paths = OmxPaths(root=root)
        tree_fp = paths.tree_yaml()
        if not tree_fp.is_file():
            return ""
        drift = campaign_drift(paths, load_tree_schema(tree_fp), Path(root))
        if drift.get("ok", True):
            return ""
        lines = ["<omx-campaign-drift>"]
        unreg = [d["group"] for d in drift.get("unregistered", [])]
        empty = [d["group"] for d in drift.get("empty_ledger", [])]
        if unreg:
            shown = ", ".join(unreg[:5]) + (" ..." if len(unreg) > 5 else "")
            lines.append(f"runs on disk but NO campaign entry: {shown}")
        if empty:
            shown = ", ".join(empty[:5]) + (" ..." if len(empty) > 5 else "")
            lines.append(f"campaign ledger EMPTY despite runs on disk: {shown}")
        lines.append(
            "Campaign state is the machine answer to 'what is done and what is "
            "left'. Fix once: `omx campaign-drift --adopt` (or `omx campaign-init "
            "--id <group>` per group); report-coverage/queue-launch keep it alive "
            "automatically afterwards.")
        lines.append("</omx-campaign-drift>")
        return "\n".join(lines)
    except Exception:
        return ""  # structurally total: covers malformed campaign_drift shapes too


# --- route_emit relevance gate (wave-17) -------------------------------------
# High-specificity experiment-domain tokens only. Deliberately excludes bare
# run/report/analyze (다의성 심각 — "run the tests"/"report a bug" false-positive;
# run is especially risky) — only verb-prefixed skill names (exp-analyze etc.)
# are included. 리포트/report stays excluded too (boundary call, spec §3.3/§5):
# marker covers the in-project case, keeping the out-of-project miss rare.
_CJK_TOKENS_EXP = ("실험", "런", "훈련", "학습 런", "재현", "퇴행", "프로파일")
_ASCII_TOKENS_EXP = (
    "omx", "experiment", "experiments", "exp-analyze", "exp-design", "exp-loop",
    "exp-init", "metrics.yaml", "wandb", "tensorboard", "checkpoint", "eval",
    "regress", "hyperparam", "proposal",
)
_EXP_ASCII_RE = re.compile(r"\b(?:" + "|".join(re.escape(t) for t in _ASCII_TOKENS_EXP) + r")\b")


#: The three omx-specific .hq/ layer subfolders (config/work/runtime each get
#: an "experiments" harness subfolder; community/ does not -- its wiki/,
#: programs/, recipes/ are shared names other harnesses could also seed, so
#: they are NOT unambiguous omx markers). Checking these, not a bare .hq/,
#: matters: .hq/ is a shared root omp/oms/omd seed too, so a bare .hq/ check
#: would read every anchored project as an omx project regardless of which
#: harness actually anchored it.
_OMX_LAYER_DIRS = (("config", "experiments"), ("work", "experiments"),
                   ("runtime", "experiments"))


def _has_omx_marker(cwd) -> bool:
    """Checkpoint-gate marker probe: cheap pathlib check ONLY -- no
    subprocess, unlike _fetch_open_backlog's resolve_omx_root ladder (which
    shells out to git). Avoids paying that cost on every prompt.

    Deliberately bare literals, not omx_paths.LEGACY_ROOT/HQ_ROOT: this probe
    must stay zero-dependency (test_handlers_import_without_omx_core poisons
    omx_core entirely and still requires this to work) and hot-path-cheap
    (no import). Exempted by name in the re-entry lint (in test_omx_paths.py).

    Checks BOTH stores: .hq/ alone (an anchored-from-scratch project, or any
    project post `--purge`) has no .omx/ at all, and a marker that only ever
    checked .omx/ would silently stop firing the checkpoint gate there —
    a live hole, not a style question, caught after this file was first
    excluded from the re-entry lint (the exclusion itself stands; it hid
    this line from a human's eye, which is the thing worth noting).

    ponytail (F2, task-5 fix-round-2, accepted not fixed): `.is_dir()`
    transparently follows a symlink, so a layer that is ITSELF a symlink
    into a different tree's real `.omx`/`.hq` is trusted as-is -- combined
    with closure_guard's Ruling-27 fallback, this gates cwd against an
    unrelated project's runs. Requires a filesystem shape (a symlinked state
    directory) that nothing in the bootstrap/CLI paths ever creates; a
    relative cwd, a bare non-experiments `.hq/` (a different harness), and a
    git worktree were all checked and do NOT false-positive. Add a
    filesystem-identity check here only if a more ordinary trigger for the
    same shape ever turns up -- see task-5-review.md Finding F2."""
    if not (isinstance(cwd, str) and cwd):
        return False
    base = Path(cwd)
    if (base / ".omx").is_dir():
        return True
    return any((base / ".hq" / a / b).is_dir() for a, b in _OMX_LAYER_DIRS)


def is_exp_related(prompt, cwd) -> bool:
    """True when the .omx/ marker is present, prompt is missing/not-a-string
    (fail-toward-inject), or any experiment-domain token matches. Never raises
    -- an internal error (marker probe included) also fails toward injection."""
    try:
        if _has_omx_marker(cwd):
            return True
        if not isinstance(prompt, str):
            return True
        lowered = prompt.lower()
        if any(tok in lowered for tok in _CJK_TOKENS_EXP):
            return True
        return bool(_EXP_ASCII_RE.search(lowered))
    except Exception:
        return True  # gate exception -> inject


def _route_gate_mode() -> str:
    import os
    try:
        v = os.environ.get("OMX_ROUTE_GATE", "off").strip().lower()
    except Exception:
        return "off"
    return v if v in ("off", "observe", "on") else "off"


def _log_would_suppress_route(prompt) -> None:
    """observe-mode audit trail (rollout §6): one stderr line per turn the gate
    would have suppressed. Best-effort — never raises, never touches stdout."""
    try:
        import hashlib
        import json as _json
        import sys
        digest = (hashlib.sha256(prompt.encode("utf-8", "replace")).hexdigest()[:16]
                  if isinstance(prompt, str) else "none")
        sys.stderr.write(_json.dumps({"decision": "would-suppress", "prompt_hash": digest}) + "\n")
    except Exception:
        pass


def _assemble_route_context(payload):
    ctx = _ROUTE_CHECKPOINT
    backlog = _fetch_open_backlog(payload)
    if backlog:
        ctx = ctx + "\n\n" + backlog
    drift = _fetch_campaign_drift(payload)
    if drift:
        ctx = ctx + "\n\n" + drift
    return {"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": ctx,
    }}


def route_emit(payload):
    mode = _route_gate_mode()
    if mode == "off":
        return _assemble_route_context(payload)  # today's unconditional inject, unchanged
    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    relevant = is_exp_related(prompt, cwd)
    if mode == "observe":
        if not relevant:
            _log_would_suppress_route(prompt)
        return _assemble_route_context(payload)  # observe never suppresses — logging only
    if not relevant:
        return None  # mode == "on": enforce
    return _assemble_route_context(payload)


# --- shared root resolution for omx_core-backed handlers ---------------------
def _omx_root(payload) -> str:
    """Resolve the omx project root (the directory holding either store,
    `.omx/` or `.hq/`) from the hook payload's cwd via the #13 ladder.
    Raises ValueError ONLY when the payload cwd is missing/empty — resolve_omx_root
    itself never raises (root.py:36 always falls back at least to cwd), so an
    unanchored cwd (stage == "cwd") is NOT an error here; it is returned like any
    other resolved root. A caller that must distinguish "genuinely no omx
    project" from "weakest-signal cwd fallback" needs the stage too (see
    _fetch_open_backlog, which checks it explicitly rather than relying on this
    helper to raise). Callers are fail-open and treat any raise as 'allow'."""
    from omx_core.root import resolve_omx_root
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        raise ValueError("hook payload carries no usable cwd")
    root, _stage = resolve_omx_root(cwd=cwd)
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

        from omx_core.omx_paths import OmxPaths, has_anchor, runtime_dir
        from omx_core.state import load_state

        paths = OmxPaths(root=_omx_root(payload))
        # anchor-gated, same branch clean.py's _clean_roots() uses — omx_dir
        # alone is unconditionally legacy and would miss .hq/ content on an
        # anchored project (store-spec §7 stage 2: no per-file fallback).
        scratch_root = (runtime_dir(paths.root) / "scratch" if has_anchor(paths.root)
                        else paths.omx_dir / "scratch")
        lines = []
        try:
            cutoff = time.time() - _NOTES_FRESH_S
            fresh = [str(p) for p in sorted(scratch_root.glob("*/notes.md"))
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
            queued = sorted(p.parent.name
                            for p in paths.runs_root().glob("*/pending-launch.json"))
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
            from omx_core.loop import FAULT_STREAK_DEFAULT, PLATEAU_DISCARDS_DEFAULT, loop_health
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
            from omx_core.ledger import LedgerCorruptError, read_run_ledger
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


# --- closure_guard (task 5): deny a closure declaration on an ungraded run --
# PreToolUse, tool_name == "Bash" only (design doc §4-6). Denies `hq post
# --category handoff`, `omx loop-disarm --reason done`, and `omx
# loop-mark-done --reason done` when this project's finished training runs are
# missing the evaluation artifacts its OWN profile declared (state
# "incomplete"), or when the gate could not tell at all (state "unreadable").
# Every other case allows (None), silently: not a closure declaration, a
# non-Bash tool, no omx project at this cwd, no run_completion contract,
# everything checked, an active human defer, a fresh satisfying receipt, or
# any internal error. A false deny here locks an operator out of closing
# their own session, and a gate that speaks in every unrelated repo on the
# machine is the Finding-8-class regression this task exists to avoid --
# hence the strict root resolver below, which short-circuits BEFORE touching
# the filesystem rather than trusting evaluate_completion to classify an
# unrelated tree correctly.
_CLOSURE_SEPARATORS = ("&&", "||", ";", "|")
_CLOSURE_SEP_RE = re.compile(r"(\|\||&&|;|\|)")
_CLOSURE_REASON_MAX_CHARS = 1200


def _closure_split_glued_separators(tokens):
    """shlex.split tokenizes on whitespace/quoting, not on shell control
    operators, so a separator with no surrounding whitespace is glued into the
    adjacent token (measured: 'cd x&&hq' -> ['cd', 'x&&hq', 'post', ...]).
    Split any token that CONTAINS '&&' '||' ';' or '|' on that substring
    before segmenting, so a real closure declaration right after a glued
    separator is never swallowed into the preceding segment.

    ponytail: this also fires inside a token that merely contains one of these
    substrings as plain text (e.g. a quoted "a;b"), over-splitting it into an
    extra segment. That is safe in the deny direction only -- an extra segment
    can match a closure command only if it reads as one verbatim -- ceiling: a
    hostile quoted argument shaped exactly like the real closure text could in
    principle create a spurious segment; not defended against here."""
    flat = []
    for tok in tokens:
        flat.extend(p for p in _CLOSURE_SEP_RE.split(tok) if p != "")
    return flat


def _closure_segments(tokens):
    """Split a token stream into command segments at &&, ||, ; and |."""
    segments = [[]]
    for tok in _closure_split_glued_separators(tokens):
        if tok in _CLOSURE_SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(tok)
    return segments


def _closure_has_adjacent(tokens, a, b) -> bool:
    return any(tokens[i] == a and tokens[i + 1] == b for i in range(len(tokens) - 1))


def _closure_kv_present(tokens, flag: str, value: str) -> bool:
    """True when `tokens` carries `flag value` as adjacent tokens, or the
    single glued token `flag=value` -- both forms this gate must recognize
    for EVERY flag it matches (Ruling 28/fix-round-1: `--category=handoff`
    was missed the same way `--reason=done` was originally handled, and a
    gate with a one-character `=`-form bypass on some flags but not others is
    the same class of hole as the separator-gluing bypass closed earlier)."""
    return _closure_has_adjacent(tokens, flag, value) or f"{flag}={value}" in tokens


def _closure_segment_declares(seg) -> bool:
    """§6: `hq post ... --category handoff` (or `--category=handoff`);
    `omx loop-disarm`/`loop-mark-done ... --reason done` (or `--reason=done`)."""
    if len(seg) < 2:
        return False
    head = (seg[0], seg[1])
    if head == ("hq", "post"):
        return _closure_kv_present(seg, "--category", "handoff")
    if head in (("omx", "loop-disarm"), ("omx", "loop-mark-done")):
        return _closure_kv_present(seg, "--reason", "done")
    return False


def _closure_read_heredoc_word(command, i, n):
    """Parse a heredoc delimiter word starting at `i` (already past any
    whitespace following `<<`/`<<-`). Quoted (`'EOF'`/`"EOF"`) or bare
    (`EOF`); returns (word_with_quotes_stripped, index_after_word). Not full
    shell word-parsing (no escape handling inside the word, no mixed
    quoting) -- sufficient for the ordinary `<<EOF` / `<<'EOF'` / `<<-EOF`
    shapes this gate needs to not be fooled by (N3, task-5 fix-round-4)."""
    if i < n and command[i] in ("'", '"'):
        q = command[i]
        j = i + 1
        start = j
        while j < n and command[j] != q:
            j += 1
        word = command[start:j]
        return word, (j + 1 if j < n else j)
    start = i
    j = i
    while j < n and not command[j].isspace() and command[j] not in ("<", ">", "|", "&", ";"):
        j += 1
    return command[start:j], j


def _closure_heredoc_terminator_exists(command, start, delim, strip_tabs) -> bool:
    """Ruling 30 (task-5 fix-round-5): whether SOME line in `command[start:]`
    exactly equals `delim` (leading tabs stripped first when `strip_tabs`).
    The pre-commitment check every candidate heredoc opener must pass BEFORE
    the scan starts treating anything as body -- see `_closure_mark_line_breaks`."""
    for line in command[start:].split("\n"):
        candidate = line.lstrip("\t") if strip_tabs else line
        if candidate == delim:
            return True
    return False


#: A `#` only starts a comment when it is the first character of a word
#: (bash's own rule) -- `echo a#b` and `url#frag` are NOT comments. Checked
#: against the raw character immediately preceding the `#`.
_CLOSURE_WORD_START_PRECEDERS = (" ", "\t", "\n", "\r", ";", "|", "&")


def _closure_mark_line_breaks(command: str) -> str:
    """Replace every line break (`\\n`, `\\r`) OUTSIDE quotes, OUTSIDE a
    `#` comment, and OUTSIDE a validated heredoc body with `;` before
    tokenizing (F1, fix-round-2), while an unquoted backslash immediately
    before one is a line CONTINUATION and vanishes instead (N1, fix-round-4):
    bash joins `verb \\<newline>  flag` into one logical line, so marking
    that newline as a separator was putting the closure verb and its own
    flag into two different segments -- exactly the shape this scan exists
    to keep together, done backwards.

    `shlex.split` treats a literal newline exactly like a space -- it is
    absorbed into inter-token whitespace and produces no token of its own --
    so a multi-line Bash `tool_input.command` (an entirely ordinary shape,
    not an adversarial one) never gets split into segments on its own, and
    the closure verb silently walks through whenever it isn't literally the
    first line. By the time you have tokens this information is already
    destroyed, so every mark below has to happen on the RAW string, before
    `shlex.split` ever runs. Once marked, the existing `;`-handling in
    `_closure_split_glued_separators` / `_closure_segments` does the rest for
    the separator case -- no other change needed there.

    Heredoc bodies (N3, fix-round-4) are DATA, not commands -- `cat > f
    <<'EOF'` followed by a body line that happens to read like a closure
    declaration must not deny, the same way a doc or a runbook showing the
    command on its own line must not deny. Tracks the region from the
    newline after `<<WORD`/`<<-WORD` (optionally quoted; `<<-` strips
    leading tabs from candidate terminator lines) through the line that
    equals WORD, copying every character in between through UNMARKED --
    option (a) from the dispatch, not the cheaper "stop marking after the
    first `<<`" option (b), because (b) would silently stop detecting a
    REAL closure command placed after a closed heredoc in the same
    command, which is the required negative case here. Multiple heredocs
    declared on one line are consumed as separate body blocks in order; the
    newline ending the FINAL terminator line (once no heredoc remains
    pending) is marked as a real separator, same as any other line break.

    Ruling 30 (fix-round-5): this scan is, at this point, a hand-rolled
    shell lexer (quotes, continuations, comments, heredocs), and a
    hand-rolled shell lexer WILL be wrong on some input -- a mis-extracted
    delimiter (a stray backslash inside it), a `<<` that was never really a
    heredoc opener at all (inside a `#` comment this scan didn't yet know
    about, or a here-string `<<<`), or a heredoc that is genuinely never
    closed. Before fix-round-5, any of those committed the scan into
    "consuming heredoc body" with NO way back out, so the entire remainder
    of the command silently became inert data -- the exact failure this
    round exists to eliminate, reproduced inside the mechanism meant to
    enforce it. The fix is a pre-commitment CHECK, not a bigger parser: a
    candidate heredoc is only entered once `_closure_heredoc_terminator_exists`
    confirms its terminator line actually appears somewhere later in the
    command; if it doesn't, this was never a heredoc opener this scan
    understood, and the newline is marked exactly as if no heredoc had been
    declared -- the scan degrades to treating the rest of the command as
    ORDINARY TEXT to keep scanning, never to silently ignoring it. That is
    the property that makes the accumulated complexity here acceptable: not
    that this lexer is correct, but that being wrong about it never turns
    into being blind for everything after.

    A `#` starting a word begins a comment running to the end of the line
    (bash's own rule -- `echo a#b` and `url#frag` are NOT comments, only a
    `#` immediately after whitespace or a separator is); nothing inside a
    comment is a heredoc opener, closing the "`<<` inside a `#` comment"
    false-negative directly rather than relying on the Ruling-30 backstop
    alone. `<<<` is a here-string (single-line, no body region), not a
    heredoc -- all three characters are consumed together so the scan never
    even attempts to parse a delimiter word for it.

    A minimal quote-aware scan otherwise, not full shell grammar -- just
    enough that a newline genuinely embedded in a quoted ARGUMENT (data,
    e.g. a multi-line `--summary`) is never mistaken for a command
    separator either. Single quotes: fully literal, nothing escapes
    (matches POSIX). Double quotes: a backslash escapes the next character,
    so an escaped `"` doesn't prematurely end the quoted span. Quote,
    comment, and continuation handling apply OUTSIDE heredoc bodies only --
    inside a validated one, everything is copied verbatim until the
    terminator line."""
    out = []
    quote = None  # None | "'" | '"' -- meaningful only outside a heredoc body
    pending_heredocs = []   # [(delim, strip_tabs)] declared on the CURRENT command line
    active_heredocs = []    # queue of heredocs currently being consumed as body, in order
    body_line_buf = []      # chars of the CURRENT heredoc body line, for terminator matching
    i, n = 0, len(command)
    while i < n:
        if active_heredocs:
            c = command[i]
            if c == "\n":
                line = "".join(body_line_buf)
                delim, strip_tabs = active_heredocs[0]
                candidate = line.lstrip("\t") if strip_tabs else line
                if candidate == delim:
                    active_heredocs.pop(0)
                    body_line_buf = []
                    out.append(c)
                    if not active_heredocs and not pending_heredocs:
                        out[-1] = ";"  # heredoc(s) done -- back to normal separator rules
                    i += 1
                    continue
                body_line_buf = []
                out.append(c)
                i += 1
                continue
            body_line_buf.append(c)
            out.append(c)
            i += 1
            continue

        c = command[i]
        if quote == "'":
            out.append(c)
            i += 1
            if c == "'":
                quote = None
            continue
        if quote == '"':
            if c == "\\" and i + 1 < n:
                out.append(c)
                out.append(command[i + 1])
                i += 2
                continue
            out.append(c)
            i += 1
            if c == '"':
                quote = None
            continue
        # unquoted context
        if c in ("'", '"'):
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "#" and (i == 0 or command[i - 1] in _CLOSURE_WORD_START_PRECEDERS):
            # a comment runs to end of line -- nothing inside it (an
            # embedded "<<EOF", a quote, a continuation) is special.
            while i < n and command[i] not in ("\n", "\r"):
                out.append(command[i])
                i += 1
            continue
        if c == "\\" and i + 1 < n and command[i + 1] in ("\n", "\r"):
            # N1: unquoted line continuation -- the backslash AND the
            # newline (CRLF counted as one) vanish, joining the two lines.
            j = i + 2
            if command[i + 1] == "\r" and j < n and command[j] == "\n":
                j += 1
            i = j
            continue
        if c == "<" and i + 1 < n and command[i + 1] == "<":
            if i + 2 < n and command[i + 2] == "<":
                # <<< here-string, not a heredoc -- consume all three chars
                # together so this never falls into delimiter parsing below.
                out.append(command[i:i + 3])
                i += 3
                continue
            j = i + 2
            strip_tabs = False
            if j < n and command[j] == "-":
                strip_tabs = True
                j += 1
            k = j
            while k < n and command[k] in (" ", "\t"):
                k += 1
            word, k2 = _closure_read_heredoc_word(command, k, n)
            if word:
                pending_heredocs.append((word, strip_tabs))
                out.append(command[i:k2])
                i = k2
                continue
            out.append(c)
            i += 1
            continue
        if c in ("\n", "\r"):
            if pending_heredocs:
                # Ruling 30: only commit to heredoc mode once every pending
                # delimiter's terminator is confirmed to exist later in the
                # command -- an opener that can never close was not a
                # heredoc opener this scan should act on.
                if all(_closure_heredoc_terminator_exists(command, i + 1, d, st)
                       for d, st in pending_heredocs):
                    active_heredocs.extend(pending_heredocs)
                    pending_heredocs = []
                    out.append(c)  # into the heredoc body -- unmarked
                else:
                    pending_heredocs = []
                    out.append(";")  # not a real heredoc -- normal separator
            else:
                out.append(";")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _closure_declares(command: str) -> bool:
    """Whether `command` contains a closure declaration in any `&&`/`||`/`;`/`|`
    segment -- a real line break counts too, marked as `;` first (F1, see
    `_closure_mark_line_breaks`). Raises ValueError on unbalanced quotes
    (shlex) -- the caller treats that as allow, same as every other internal
    failure (D9).

    ponytail: the closure verb must still be the literal head of its
    segment, so `env FOO=1 hq post ...`, `sudo hq post ...`,
    `command hq post ...`, and `x=$(hq post ...)` all still bypass this
    gate. Accepted, not fixed: each requires deliberately dressing up the
    command to evade an ADVISORY, fail-open gate -- the same class as a
    shell `alias`, which cannot be resolved without a shell either -- and a
    determined operator always has the honest escape,
    `omx close-defer --reason "<why>"`. Widen to "closure verb anywhere as a
    contiguous subsequence in its segment" if one of these ever turns out to
    be an ordinary shape (like the newline case was) rather than a
    deliberate one."""
    import shlex
    tokens = shlex.split(_closure_mark_line_breaks(command))
    return any(_closure_segment_declares(seg) for seg in _closure_segments(tokens))


def _closure_fit_reason(header: str, body: str, footer: str) -> str:
    """Assemble header/body/footer under the 1200-char permissionDecisionReason
    budget (Ruling 3). The per-state assembly rules (at most 3 run blocks, a
    shared `how` printed once) already keep this well under budget in
    practice; this is a safety net for unusually long paths/globs, and it
    trims the body ONLY -- the header (why) and the footer (the close-defer
    escape hatch) must always survive intact."""
    text = f"{header}\n\n{body}\n\n{footer}" if body else f"{header}\n\n{footer}"
    if len(text) <= _CLOSURE_REASON_MAX_CHARS:
        return text
    budget = _CLOSURE_REASON_MAX_CHARS - len(header) - len(footer) - 4  # 2x "\n\n"
    if budget <= 0:
        return (header + "\n\n" + footer)[:_CLOSURE_REASON_MAX_CHARS]
    return f"{header}\n\n{body[:budget].rstrip()}\n\n{footer}"


_CLOSURE_INCOMPLETE_HEADER = (
    "omx run-completion gate: this closure declaration is blocked because a finished\n"
    "training run has none of the evaluation artifacts this project's profile declares."
)
_CLOSURE_INCOMPLETE_FOOTER = (
    "The contract is yours, in profile/metrics.yaml under `run_completion`; the harness only\n"
    "checks that a finished run has what you declared. Produce the artifacts, or record why\n"
    "you are not: `omx close-defer --reason \"<why>\"`."
)


def _closure_incomplete_reason(verdict: dict) -> str:
    missing = verdict["missing"]
    shown = missing[:3]
    extra = len(missing) - len(shown)
    hows = {m["how"] for m in shown}
    same_how = len(hows) == 1
    lines = []
    for m in shown:
        lines.append(f"  {m['run']}   missing: {', '.join(m['missing'])}")
        if not same_how:
            lines.append(f"               make it: {m['how']}")
    if extra > 0:
        lines.append(f"  (+{extra} more — `omx close-check` lists them all)")
    if same_how:
        lines.append("")
        lines.append(f"  make it: {next(iter(hows))}")
    return _closure_fit_reason(_CLOSURE_INCOMPLETE_HEADER, "\n".join(lines),
                               _CLOSURE_INCOMPLETE_FOOTER)


_CLOSURE_UNREADABLE_HEADER = (
    "omx run-completion gate: this closure declaration is blocked because the gate could not\n"
    "determine whether this project's finished runs are graded."
)
_CLOSURE_UNREADABLE_FOOTER = (
    "If the reason names a profile key instead of a path, fix profile/metrics.yaml. To\n"
    "proceed without either: omx close-defer --reason \"<why>\"."
)


def _closure_unreadable_reason(verdict: dict, root) -> str:
    # `reason` is printed verbatim -- it already names the failing path or the
    # offending profile key, and a paraphrase loses that (task-5-deny-text §2).
    reason_text = verdict.get("reason") or "(no reason recorded)"
    body = (
        f"  reason: {reason_text}\n\n"
        "This is not \"nothing to grade\" — an unread tree and an empty one are different "
        "answers,\nand only one of them is a pass. If the output tree lives on another "
        "machine, run the\ncheck where it lives and bring the receipt back:\n\n"
        f"  ssh <host> 'omx close-check --root {root} --json'  |  omx close-ack --from -"
    )
    return _closure_fit_reason(_CLOSURE_UNREADABLE_HEADER, body, _CLOSURE_UNREADABLE_FOOTER)


def _closure_resolve_root(payload) -> str:
    """Resolve the omx root for closure_guard (Ruling 27, fix-round-1).

    The #13 ladder (`resolve_omx_root`) as usual -- but its stage "cwd" means
    only "no explicit root / OMX_STATE_DIR / .omx-workspace marker / git
    toplevel found"; the ladder never checks for an omx LAYER (`.omx/` or a
    `.hq/` layer dir) at all, so "the ladder found no anchor" is NOT the same
    fact as "there is no omx project here" -- conflating those two was
    exactly the bug this round shipped once already (a directory with a
    bootstrapped profile and a real, unevaluated finished run allowed every
    closure command, because the ladder alone was trusted to say "no
    project"). A project that opted in (its own store is present) but sits
    outside git and without a marker is a real omx project and must still be
    gated: when the ladder lands on stage "cwd", fall back to
    `_has_omx_marker(cwd)` -- the existing bare-pathlib, zero-subprocess probe
    that already checks BOTH stores (shared with the route_emit checkpoint
    gate) -- and gate against `cwd` itself if it finds one. Only when
    NEITHER the ladder anchors NOR an omx layer is present at cwd does this
    raise, which the caller treats as allow: an unrelated directory on the
    machine must never be gated (the Finding-8 regression class).

    A dedicated resolver, deliberately NOT a change to `_resolve_backlog_root`:
    that one backs the route_emit backlog pre-fetch / campaign-drift check, a
    different call site with its own already-shipped, tested contract
    (`test_hook_backlog.py` monkeypatches it by NAME) -- widening its
    anchoring was not part of this task, and giving closure_guard its own
    function keeps that contract untouched.

    ponytail: `_has_omx_marker` does not climb toward a parent directory the
    way the ladder's OWN marker stage does -- a cwd one level below a
    bootstrapped project's root still falls through to allow here, same as
    it already does for the existing route_emit checkpoint-gate probe this
    reuses. Left alone deliberately for consistency with that shared probe's
    existing meaning; climb (or resolve via OmxPaths' own layer-detection
    walk) if a real cwd-below-root closure attempt ever turns up."""
    from omx_core.root import resolve_omx_root
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        raise ValueError("hook payload carries no usable cwd")
    root, stage = resolve_omx_root(cwd=cwd)
    if stage == "cwd" and not _has_omx_marker(cwd):
        raise ValueError(f"no omx root anchor or layer found for cwd {cwd!r}")
    return str(root)


def closure_guard(payload):
    try:
        if payload.get("tool_name") != "Bash":
            return None
        command = (payload.get("tool_input") or {}).get("command")
        if not isinstance(command, str) or not command:
            return None
        if not _closure_declares(command):
            return None

        from omx_core.clock import now_iso
        from omx_core.completion import (active_defer, evaluate_completion,
                                          read_receipt, receipt_satisfies)
        from omx_core.omx_paths import OmxPaths

        root = _closure_resolve_root(payload)  # raises on no anchor AND no omx layer
        paths = OmxPaths(root=root)
        now = now_iso()

        if active_defer(paths, now):
            return None
        if receipt_satisfies(read_receipt(paths), now, expected_root=paths.root):
            return None

        verdict = evaluate_completion(paths)
        state = verdict["state"]
        if state in ("no-contract", "checked"):
            return None
    except Exception:
        return None  # fail-open (D9): an infra/setup failure BEFORE a verdict exists allows

    # F4 (task-5 fix-round-2): evaluate_completion has ALREADY decided this
    # command must be denied -- a bug in the TEXT-RENDERING code that turns
    # that verdict into the reason string must not silently downgrade an
    # already-made deny into an allow. D9's fail-open is for infrastructure
    # failures upstream of a verdict (root resolution, defer/receipt reads,
    # evaluate_completion itself, all still covered by the try/except
    # above); a formatting bug in code that runs AFTER the decision is a
    # different failure class and must still deny, minimally.
    try:
        reason = (_closure_incomplete_reason(verdict) if state == "incomplete"
                  else _closure_unreadable_reason(verdict, paths.root))
    except Exception:
        reason = ("omx run-completion gate: this closure declaration is blocked, but the "
                   "deny-reason renderer itself failed -- run `omx close-check` for the real "
                   "verdict, or `omx close-defer --reason \"<why>\"` to proceed.")
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}


HANDLERS = {
    "report_guard": report_guard,
    "route_emit": route_emit,
    "capture_flush": capture_flush,
    "compact_breadcrumb": compact_breadcrumb,
    "loop_gate": loop_gate,
    "closure_guard": closure_guard,
}
