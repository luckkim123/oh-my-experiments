# v0.4.0 live hook-fire acceptance (spec 3 — run AFTER plugin reinstall + pip install -e)

Claude-free pytest cannot prove the platform fires the events or honors the
output schemas. Execute in a real Claude Code session on this repo and record
observed results here (evidence for the spec's platform-contract assumptions):

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
