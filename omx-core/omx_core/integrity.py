"""omx_core.integrity — sha256 stamp/verify for gated analysis deliverables (#14).

Stamper = verifier, one call: report-coverage stamps the manifest in the same
invocation that passes the gates, so there is no separate "who verifies the
verifier" window. The manifest is ALWAYS the report's SIBLING
(dirname(report)/manifest.json) — no verb takes run_id/analysis_id for this
(spec 3.3 path contract).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from omx_core.omx_paths import atomic_path, validate_analysis_id

_HASHED_FILES = ("report.md", "report.ko.md")


def manifest_path_for(report_path) -> Path:
    return Path(report_path).parent / "manifest.json"


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_analysis_report(report_path) -> bool:
    """True iff the report sits at .../analysis/<analysis_id>/report*.md."""
    p = Path(report_path)
    try:
        validate_analysis_id(p.parent.name)
    except Exception:
        return False
    return p.parent.parent.name == "analysis"


def stamp_report(report_path, *, gates_passed, now, omx_version) -> dict:
    report_path = Path(report_path)
    mpath = manifest_path_for(report_path)
    manifest = {}
    if mpath.exists():
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    hashes = {}
    for name in _HASHED_FILES:
        fp = report_path.parent / name
        if fp.exists():
            hashes[name] = file_sha256(fp)
    stamp = {
        "file_sha256": hashes,
        "gates_passed": list(gates_passed),
        "omx_version": omx_version,
        "stamped_at": now,
    }
    manifest["integrity"] = stamp
    with atomic_path(mpath) as tmp:
        Path(tmp).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return stamp


def verify_report(path) -> dict:
    """path = report.md OR its analysis dir. Recompute hashes vs the stamp."""
    p = Path(path)
    adir = p if p.is_dir() else p.parent
    mpath = adir / "manifest.json"
    out = {"status": "ok", "mismatched": [], "manifest": str(mpath)}
    if not mpath.exists():
        out["status"] = "unstamped"
        return out
    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    except ValueError:
        out["status"] = "mismatch"
        out["mismatched"] = ["manifest.json"]
        return out
    stamp = manifest.get("integrity")
    if not isinstance(stamp, dict) or not stamp.get("file_sha256"):
        out["status"] = "unstamped"
        return out
    for name, recorded in stamp["file_sha256"].items():
        fp = adir / name
        if not fp.exists() or file_sha256(fp) != recorded:
            out["mismatched"].append(name)
    if out["mismatched"]:
        out["status"] = "mismatch"
        return out
    if not stamp.get("gates_passed"):
        out["status"] = "no-gates"
    return out
