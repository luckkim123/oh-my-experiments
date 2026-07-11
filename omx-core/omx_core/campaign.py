"""omx_core.campaign — the cross-run campaign ledger (#28, spec 2.9).

campaign_id IS the tree's <group> segment (D-R2-5): one name across the tree
layer, the wandb project, and this ledger. Append-only jsonl, one event per
line; single-writer assumption documented (the R4 concurrency lock will cover
multi-writer). Nothing here launches anything (D4)."""
from __future__ import annotations

import json

from omx_core.omx_paths import OmxError, OmxPaths, atomic_path


class CampaignError(OmxError):
    """Loud-fail for campaign misuse (exists/uninitialized/bad event)."""


EVENTS = ("launched", "kept", "discarded", "eval", "note")


def init_campaign(paths: OmxPaths, campaign_id, *, now, goal=None,
                  baseline_run_id=None, extra=None) -> dict:
    d = paths.campaign_dir(campaign_id)
    if d.exists():
        raise CampaignError(f"campaign {campaign_id!r} already exists at {d}")
    d.mkdir(parents=True)
    plan = {"campaign_id": campaign_id, "created": now}
    if goal:
        plan["goal"] = goal
    if baseline_run_id:
        plan["baseline_run_id"] = baseline_run_id
    if extra:
        for k, v in extra.items():
            plan.setdefault(k, v)
    with atomic_path(paths.campaign_plan(campaign_id)) as tmp:
        tmp.write_text(json.dumps(plan, indent=2))
    paths.campaign_ledger(campaign_id).touch()
    return plan


def plan_add(paths: OmxPaths, campaign_id, *, proposal_id, summary=None, now) -> dict:
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
                    "added_at": now})
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
            "added_at": entry.get("added_at"),
            "derived_status": derived,
        })
    return {"campaign_id": campaign_id, "plan": plan_view, "counts": counts,
            "runs": runs, "last": events[-1] if events else None}


def list_campaigns(paths: OmxPaths) -> list:
    root = paths.omx_dir / "campaigns"
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or not (d / "plan.json").is_file():
            continue
        try:
            plan = json.loads((d / "plan.json").read_text())
        except ValueError:
            plan = {}
        ledger = d / "ledger.jsonl"
        n = len(ledger.read_text().splitlines()) if ledger.is_file() else 0
        out.append({"campaign_id": d.name, "created": plan.get("created"),
                    "events": n})
    return out
