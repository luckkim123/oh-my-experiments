# v0.4.0 live hook-fire acceptance (spec 3 — run AFTER plugin reinstall + pip install -e)

Claude-free pytest cannot prove the platform fires the events or honors the
output schemas. Execute in a real Claude Code session on this repo and record
observed results here (evidence for the spec's platform-contract assumptions):

## CLI/handler-level pre-verification (controller, isolated temp root, 2026-07-07)

Not a substitute for the platform-fire checks below — these confirm the CLI +
handler LOGIC in isolation; the platform must still be observed to actually
FIRE each event. Editable install confirmed live (omx_core loads from
`omx-core/omx_core`, `omx` on PATH), so `pip install -e` re-run is a no-op.

- [x] loop_gate LOGIC: `omx loop-arm --root <tmp> --run-id probe --max-runtime 600`
      persists `<tmp>/.omx/state.json` with the 6-key envelope
      `{run_id, armed_at, deadline(aware +00:00), iteration:0, hard_cap:50,
      adopted_session:null}`; calling `loop_gate({cwd:<tmp>, session_id:sess-ABC})`
      returned `decision: block`, the continuation contained the D4 sentence
      ("NEVER execute a training launch"), and iteration incremented to 1
      (proving the gate read the arm-written state). `omx loop-disarm` returned
      `{was_armed:true, iteration:0, reason:done}`.
- [x] kill switch LOGIC: `run_hook.py:62/67` — `OMX_DISABLE=1` short-circuits ALL
      handlers to no-op; `OMX_SKIP_HOOKS=a,b` no-ops named handlers.
- [x] route_emit / capture_flush / compact_breadcrumb handler RETURN values are
      pytest-covered (test_hook_handlers_r3 / test_capture_flush / test_loop_gate);
      what remains unproven is only the PLATFORM actually firing them (below).

## Platform-fire checks (HUMAN-run in a fresh Claude Code session — controller CANNOT self-verify these)

Each requires the platform to fire a real hook event and the session to observe
the result; a controller cannot run these without trapping/mutating its own
working session (arming the gate on itself, self-compacting, ending itself):

- [ ] route_emit: a fresh prompt shows the <omx-routing> STAGE block.
- [ ] loop_gate: `omx loop-arm --run-id probe --max-runtime 600` -> ending a
      turn is blocked with the continuation prompt (containing the D4
      sentence); `omx loop-disarm` -> the next stop is allowed. Confirm the
      arming session was adopted (state.json adopted_session set).
- [ ] capture_flush: stamp a report (report-coverage on a fixture), end the
      session -> session-log stub pages exist; shutdown was not visibly
      delayed (async honored). If shutdown IS delayed ~flush-time, record
      "async ignored — synchronous fallback in effect (accepted, spec 2.2)".
- [ ] compact_breadcrumb: with a fresh scratch notes.md present, /compact ->
      the first post-compaction prompt carries <omx-durable-state>.
- [ ] kill switch: OMX_DISABLE=1 silences all of the above.

## v0.5.0 (R4) live acceptance (append — R3 checkboxes above are untouched)

R4 adds one platform-dependent behavior beyond R3: the `loop_gate` circuit
self-disarm (plateau/fault_circuit) — checkable in the same armed-session probe
as R3's pending `loop_gate` item. Everything else in R4 is Claude-free CLI logic
proven by pytest.

- [ ] loop_gate circuit backstop: seed a run ledger with 5 consecutive discards
      (`omx run-seed` + 5 `omx run-record --decision discard`), arm the gate,
      then end a turn -> the gate self-disarms with reason `plateau` (the
      completion marker records it) and the next stop is allowed. Repeat with 3
      consecutive evaluator faults for `fault_circuit`.
- [x] route_emit platform-fire OBSERVED LIVE 2026-07-11: the `<omx-routing>`
      STAGE block was injected into this authoring session (plugin v0.4.0;
      route_emit is R3 code unchanged by R4, so this is real observed evidence,
      not a pre-mark), closing the corresponding R3 checkbox (record here; do
      not edit the R3 list above — this line is the evidence). All other
      v0.5.0 boxes stay unchecked until run after plugin reinstall.
