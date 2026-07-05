"""omx_core.seal — evaluator/launch seal (#0, spec 3.5).

`profile-seal` records sha256 of the PROFILE FILES at approval time; `omx eval`
preflights the CURRENT hashes against the seal before running anything. The
check never inspects the eval --command string — the seal guards the files the
skills are instructed to execute. Mid-loop evaluator edits therefore surface as
rc 2 instead of silently changing the grading criteria.
"""
from __future__ import annotations

import json
from pathlib import Path

from omx_core.integrity import file_sha256
from omx_core.omx_paths import OmxError, OmxPaths, atomic_path

_SEALED = ("evaluator.sh", "launch.sh")


def write_seal(paths: OmxPaths, *, now: str) -> dict:
    hashes = {}
    for name in _SEALED:
        fp = paths.profile_dir / name
        if fp.exists():
            hashes[name] = file_sha256(fp)
    if "evaluator.sh" not in hashes:
        raise OmxError(
            f"no evaluator.sh at {paths.profile_dir}; run exp-init first")
    seal = {"file_sha256": hashes, "sealed_at": now}
    with atomic_path(paths.seal_json()) as tmp:
        Path(tmp).write_text(json.dumps(seal, indent=2), encoding="utf-8")
    return seal


def check_seal(paths: OmxPaths) -> dict:
    sp = paths.seal_json()
    if not sp.exists():
        return {"status": "absent", "mismatched": [], "sealed_at": None}
    try:
        seal = json.loads(sp.read_text(encoding="utf-8"))
        recorded = seal.get("file_sha256") or {}
    except ValueError:
        return {"status": "mismatch", "mismatched": ["seal.json"], "sealed_at": None}
    mismatched = []
    for name, digest in recorded.items():
        fp = paths.profile_dir / name
        if not fp.exists() or file_sha256(fp) != digest:
            mismatched.append(name)
    return {"status": "mismatch" if mismatched else "ok",
            "mismatched": mismatched, "sealed_at": seal.get("sealed_at")}
