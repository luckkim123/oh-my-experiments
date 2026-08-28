"""omx_core.campaign — the cross-run campaign ledger (#28, spec 2.9).

campaign_id IS the tree's <group> segment (D-R2-5): one name across the tree
layer, the wandb project, and this ledger. Append-only jsonl, one event per
line; single-writer assumption documented (the R4 concurrency lock will cover
multi-writer). Nothing here launches anything (D4)."""
from __future__ import annotations

import json
from pathlib import Path

from omx_core.omx_paths import (
    OmxError,
    OmxPaths,
    atomic_path,
    config_dir,
    iter_store_entries,
)


class CampaignError(OmxError):
    """Loud-fail for campaign misuse (exists/uninitialized/bad event)."""


EVENTS = ("launched", "kept", "discarded", "eval", "note", "analyzed")


def init_campaign(paths: OmxPaths, campaign_id, *, now, goal=None,
                  baseline_run_id=None, predecessor=None, extra=None) -> dict:
    d = paths.campaign_dir(campaign_id)
    if d.exists():
        raise CampaignError(f"campaign {campaign_id!r} already exists at {d}")
    d.mkdir(parents=True)
    plan = {"campaign_id": campaign_id, "created": now}
    if goal:
        plan["goal"] = goal
    if baseline_run_id:
        plan["baseline_run_id"] = baseline_run_id
    if predecessor:
        plan["predecessor"] = predecessor
    if extra:
        for k, v in extra.items():
            plan.setdefault(k, v)
    with atomic_path(paths.campaign_plan(campaign_id)) as tmp:
        tmp.write_text(json.dumps(plan, indent=2))
    paths.campaign_ledger(campaign_id).touch()
    return plan


def plan_add(paths: OmxPaths, campaign_id, *, proposal_id, summary=None,
             label=None, now) -> dict:
    """Append a planned proposal to plan.json's `planned` list (intent — D-R4-10).
    plan.json is the replayable statement of what exp-design decided to try;
    ledger.jsonl records what happened. Duplicate proposal_id loud-fails (a
    proposal is planned once). Atomic rewrite. Returns the updated plan dict."""
    plan_path = paths.campaign_plan(campaign_id)
    if not plan_path.is_file():
        raise CampaignError(
            f"campaign {campaign_id!r} not initialized — run `omx campaign-init "
            f"--id {campaign_id}` first")
    plan = json.loads(plan_path.read_text())
    planned = plan.setdefault("planned", [])
    if any(e.get("proposal_id") == proposal_id for e in planned):
        raise CampaignError(
            f"proposal {proposal_id!r} already planned in campaign {campaign_id!r} "
            "(a proposal is planned once)")
    planned.append({"proposal_id": proposal_id, "summary": summary or "",
                    "label": label or "", "added_at": now})
    with atomic_path(plan_path) as tmp:
        tmp.write_text(json.dumps(plan, indent=2))
    return plan


def append_event(paths: OmxPaths, campaign_id, *, now, event, run_id=None,
                 session_id=None, data=None) -> dict:
    if event not in EVENTS:
        raise CampaignError(f"event must be one of {EVENTS}, got {event!r}")
    if not paths.campaign_dir(campaign_id).is_dir():
        raise CampaignError(
            f"campaign {campaign_id!r} not initialized — run `omx campaign-init "
            f"--id {campaign_id}` first (explicit-init discipline)")
    rec = {"ts": now, "event": event}
    if run_id:
        rec["run_id"] = run_id
    if session_id:
        rec["session_id"] = session_id
    if data is not None:
        rec["data"] = data
    line = json.dumps(rec)
    if "\n" in line:
        raise CampaignError("ledger record serialized with a newline (refused)")
    with open(paths.campaign_ledger(campaign_id), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return rec


def read_ledger(paths: OmxPaths, campaign_id) -> list:
    if not paths.campaign_dir(campaign_id).is_dir():
        raise CampaignError(f"campaign {campaign_id!r} not initialized")
    fp = paths.campaign_ledger(campaign_id)
    out = []
    if fp.is_file():
        for line in fp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"event": "_corrupt", "raw": line})
    return out


def campaign_status(paths: OmxPaths, campaign_id) -> dict:
    events = read_ledger(paths, campaign_id)
    counts, runs = {}, []
    for e in events:
        ev = e.get("event", "_corrupt")
        counts[ev] = counts.get(ev, 0) + 1
        rid = e.get("run_id")
        if rid and rid not in runs:
            runs.append(rid)
    plan_path = paths.campaign_plan(campaign_id)
    if not plan_path.is_file():
        raise OmxError(
            f"campaign {campaign_id!r} has no plan.json at {plan_path} — was it "
            "initialized with `omx campaign-init`?")
    plan = json.loads(plan_path.read_text())
    # derive per-proposal status at read time (D-R4-10): join `planned` against
    # ledger events by data.proposal / data.proposal_id — status is NEVER
    # written into plan.json (one SSOT per fact).
    outcome = {}
    for e in events:
        data = e.get("data") or {}
        pid = data.get("proposal") or data.get("proposal_id")
        ev = e.get("event")
        # only terminal events settle an outcome (last TERMINAL event wins) —
        # a later eval/note on the same proposal_id must not regress a
        # kept/discarded/launched proposal back to "planned".
        if pid and ev in ("kept", "discarded", "launched"):
            outcome[pid] = ev
    plan_view = []
    for entry in plan.get("planned", []):
        pid = entry.get("proposal_id")
        ev = outcome.get(pid)
        derived = ev if ev in ("kept", "discarded", "launched") else "planned"
        plan_view.append({
            "proposal_id": pid,
            "summary": entry.get("summary", ""),
            "label": entry.get("label", ""),
            "added_at": entry.get("added_at"),
            "derived_status": derived,
        })
    return {"campaign_id": campaign_id, "plan": plan_view, "counts": counts,
            "runs": runs, "last": events[-1] if events else None}


def list_campaigns(paths: OmxPaths) -> list:
    """Lists the single anchor-resolved campaigns root (store-spec §7 stage 2)."""
    entries = iter_store_entries(paths.campaigns_root())
    out = []
    for name in sorted(entries):
        d = entries[name]
        if not d.is_dir() or not (d / "plan.json").is_file():
            continue
        try:
            plan = json.loads((d / "plan.json").read_text())
        except ValueError:
            plan = {}
        ledger = d / "ledger.jsonl"
        n = len(ledger.read_text().splitlines()) if ledger.is_file() else 0
        entry = {"campaign_id": name, "created": plan.get("created"),
                 "events": n}
        if plan.get("predecessor"):
            entry["predecessor"] = plan["predecessor"]
        out.append(entry)
    return out


def record_analyzed(paths: OmxPaths, report_path, *, now) -> dict:
    """Byproduct event for a gated report (v0.8.0 campaign liveness).

    Derives run_id/group from the report's tree position (caller has already
    passed is_analysis_report), auto-inits the group campaign when absent, and
    appends one `analyzed` event. Dedup by resolved report path — the coverage
    verb re-runs on the same report and must not spam the ledger."""
    p = Path(report_path).resolve()
    run_dir = p.parents[2]
    group = run_dir.parent.name
    if not paths.campaign_dir(group).is_dir():
        init_campaign(paths, group, now=now,
                      extra={"auto_initialized": True,
                             "source": "report-coverage"})
    for e in read_ledger(paths, group):
        if (e.get("event") == "analyzed"
                and (e.get("data") or {}).get("report") == str(p)):
            return {"status": "duplicate", "campaign_id": group}
    rec = append_event(paths, group, now=now, event="analyzed",
                       run_id=run_dir.name, data={"report": str(p)})
    return {"status": "logged", "campaign_id": group, "event": rec}


def record_launched(paths: OmxPaths, proposal_id, run_id, *, now) -> dict:
    """Byproduct `launched` event at queue-launch time (v0.8.0).

    Appends to the campaign whose plan.json planned this proposal_id — NOT the
    run's group — so the plan-to-outcome join survives a campaign that spans
    groups. Dedup by (proposal_id, run_id)."""
    entries = iter_store_entries(paths.campaigns_root())
    for name in sorted(entries):
        d = entries[name]
        plan_fp = d / "plan.json"
        if not d.is_dir() or not plan_fp.is_file():
            continue
        try:
            plan = json.loads(plan_fp.read_text())
        except ValueError:
            continue
        if not any(e.get("proposal_id") == proposal_id
                   for e in plan.get("planned", [])):
            continue
        for e in read_ledger(paths, name):
            if (e.get("event") == "launched" and e.get("run_id") == run_id
                    and (e.get("data") or {}).get("proposal_id") == proposal_id):
                return {"status": "duplicate", "campaign_id": name}
        rec = append_event(paths, name, now=now, event="launched",
                           run_id=run_id,
                           data={"proposal_id": proposal_id,
                                 "source": "queue-launch"})
        return {"status": "logged", "campaign_id": name, "event": rec}
    return {"status": "unplanned", "campaign_id": None}


def campaign_drift(paths: OmxPaths, schema, base) -> dict:
    """Runs-on-disk vs .omx/campaigns/ drift (v0.8.0). Report-only.

    (a) unregistered — an index-tree group holds runs but no campaign dir;
    (b) empty_ledger — the campaign exists, its group holds runs, the ledger
    has 0 events. Exactly the July-2026 field condition that doctor/tree-audit
    never saw. Group = the run dir's parent segment (D-R2-5)."""
    from omx_core.tree import runs_at_declared_depth, walk_runs
    groups = {}
    for e in runs_at_declared_depth(walk_runs(schema, Path(base))):
        if e["role"] != "index":
            continue
        run = Path(e["path"])
        groups.setdefault(run.parent.name, []).append(run.name)
    unregistered, empty = [], []
    for g in sorted(groups):
        try:
            cdir = paths.campaign_dir(g)
        except OmxError:
            continue  # parent segment not campaign-id-shaped (e.g. tree root)
        if not cdir.is_dir():
            unregistered.append({"group": g, "runs": len(groups[g])})
            continue
        ledger = paths.campaign_ledger(g)
        n = 0
        if ledger.is_file():
            n = sum(1 for ln in
                    ledger.read_text(encoding="utf-8").splitlines()
                    if ln.strip())
        if n == 0:
            empty.append({"group": g, "runs": len(groups[g])})
    return {"ok": not unregistered and not empty,
            "unregistered": unregistered, "empty_ledger": empty}


def adopt_drift(paths: OmxPaths, schema, base, *, now) -> dict:
    """One-shot remediation for campaign_drift: init missing campaigns and
    append one `note {kind: adopted}` to empty ledgers. Idempotent — a second
    run adopts nothing."""
    drift = campaign_drift(paths, schema, base)
    adopted = []
    for item in drift["unregistered"] + drift["empty_ledger"]:
        g = item["group"]
        if not paths.campaign_dir(g).is_dir():
            init_campaign(paths, g, now=now,
                          extra={"auto_initialized": True,
                                 "source": "campaign-drift --adopt"})
        append_event(paths, g, now=now, event="note",
                     data={"kind": "adopted",
                           "source": "campaign-drift --adopt"})
        adopted.append(g)
    return {"adopted": adopted, "drift_before": drift}


# --- program layer (v0.9.0): cross-campaign view over the group-keyed store ---

def init_program(paths: OmxPaths, program_id, campaigns, *, now) -> dict:
    """Create .omx/programs/<program_id>/program.json, or attach members to it.

    `campaigns` may be empty: a research line is planned BEFORE its first run
    exists, so the program has to be openable with zero members (the PLAN.md
    is the point, the campaigns arrive later). Re-running with `--campaigns`
    on an existing program APPENDS the new members — that is the attach-later
    path, and it is append-only so a re-run can never drop a member.

    PLAN.md and HANDOFF.md are seeded from the program templates when absent, so
    a plan starts with the sections `program-lint` gates (objective verbatim,
    decision list, predicted outcome). An existing file is NEVER overwritten —
    the git-mv migration path for a pre-existing narrative still works, and the
    lint tells that plan what it is missing.
    """
    from omx_core.program import HANDOFF_TEMPLATE, PLAN_TEMPLATE
    missing = [c for c in campaigns if not paths.campaign_plan(c).is_file()]
    if missing:
        raise CampaignError(
            f"member campaign(s) not initialized: {missing} — "
            "run campaign-init first")
    d = paths.program_dir(program_id)
    pj = paths.program_json(program_id)
    if pj.is_file():
        header = json.loads(pj.read_text())
        known = header.get("campaigns", [])
        header["campaigns"] = known + [c for c in campaigns if c not in known]
    elif d.exists():
        raise CampaignError(f"program {program_id!r} already exists at {d}")
    else:
        d.mkdir(parents=True)
        header = {"program_id": program_id, "campaigns": list(campaigns),
                  "status": "active", "created": now}
    with atomic_path(pj) as tmp:
        tmp.write_text(json.dumps(header, indent=2))
    for name, tpl in (("PLAN.md", PLAN_TEMPLATE), ("HANDOFF.md", HANDOFF_TEMPLATE)):
        target = d / name
        if not target.exists():
            with atomic_path(target) as tmp:
                tmp.write_text(tpl.format(program_id=program_id))
    return header


def list_programs(paths: OmxPaths) -> list:
    """Lists the single anchor-resolved programs root (store-spec §7 stage
    2). programs_root() alone is NOT sufficient: it enumerates the
    community/ (narrative) layer, but a program whose only file is
    program.json under config/experiments/programs/<id>/ has no matching
    community/ entry yet — so also scan the config-layer programs root
    directly (an unanchored project has no config/community split, and is
    already fully covered by programs_root()'s legacy resolution) and settle
    every candidate id by asking program_json() itself whether it exists."""
    ids = set(iter_store_entries(paths.programs_root()))
    config_programs_root = config_dir(paths.root) / "programs"
    if config_programs_root.is_dir():
        ids.update(d.name for d in config_programs_root.iterdir() if d.is_dir())
    return sorted(i for i in ids if paths.program_json(i).is_file())


def program_status(paths: OmxPaths, program_id=None) -> dict:
    """Aggregate member campaigns' status into one cross-group view.

    Read-only over the campaign store; a vanished member degrades to an
    error entry instead of killing the view.
    """
    if program_id is None:
        ids = list_programs(paths)
        if len(ids) != 1:
            raise CampaignError(
                f"--id required (programs found: {ids if ids else 'none'})")
        program_id = ids[0]
    pj = paths.program_json(program_id)
    if not pj.is_file():
        raise CampaignError(
            f"program {program_id!r} has no program.json at {pj} — was it "
            "initialized with `omx program-init`?")
    header = json.loads(pj.read_text())
    members = []
    for cid in header.get("campaigns", []):
        try:
            members.append(campaign_status(paths, cid))
        except OmxError as e:
            members.append({"campaign_id": cid, "error": str(e)})
    return {"program_id": program_id,
            "status": header.get("status", "active"),
            "plan_md": paths.program_plan_md(program_id).is_file(),
            "campaigns": members}
