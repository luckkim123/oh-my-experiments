#!/usr/bin/env python3
"""Report git-tag drift against the declared plugin version (read-only).

Ported from oh-my-scholar's `scripts/sync_version.py` tag-drift check —
same semantics, adapted to this repo's version source
(`.claude-plugin/plugin.json`, mirrored by CHANGELOG.md's top released
entry; `omx-core/pyproject.toml` sync is a separate, already-covered
surface in `omx-core/tests/test_version_sync.py`).

Surfaces: ① `.claude-plugin/plugin.json` `version` — the anchor.
② CHANGELOG.md top *released* entry (`## [Unreleased]` skipped).
③ the latest `v*` git tag (exact `vMAJOR.MINOR.PATCH` match only,
max by numeric tuple).

Pre-tag window: right after a CHANGELOG/plugin.json bump but before the
release tag is cut, `latest_tag` still equals the *previous* release —
that is expected (release-in-progress), not drift, so the tag surface
accepts either the current or the previous released version. Two or
more versions behind is drift. A repo with no `v*` tags at all skips
the tag surface entirely rather than failing (young repo).

This CLI is read-only: it never edits plugin.json or CHANGELOG.md.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
CHANGELOG_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\]")


def parse_changelog(path) -> list:
    """Released version strings, top-to-bottom, `## [Unreleased]` skipped."""
    text = Path(path).read_text(encoding="utf-8")
    return [m.group(1) for line in text.splitlines() if (m := CHANGELOG_RE.match(line))]


def parse_tags(tags):
    """Latest exact `vMAJOR.MINOR.PATCH` tag by numeric tuple, or None."""
    best, best_tuple = None, None
    for t in tags:
        m = TAG_RE.match(t)
        if not m:
            continue
        tup = tuple(int(x) for x in m.groups())
        if best_tuple is None or tup > best_tuple:
            best, best_tuple = t, tup
    return best


def gather(repo_root) -> dict:
    """Read the plugin.json / CHANGELOG.md / git-tag surfaces."""
    repo_root = Path(repo_root)
    plugin = json.loads(
        (repo_root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )["version"]

    versions = parse_changelog(repo_root / "CHANGELOG.md")
    changelog_top = versions[0] if versions else None
    changelog_prev = versions[1] if len(versions) > 1 else None

    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "tag", "-l", "v*"],
            capture_output=True, text=True, check=True,
        ).stdout
        latest_tag = parse_tags([t for t in out.splitlines() if t.strip()])
    except (subprocess.CalledProcessError, OSError):
        latest_tag = None

    return {
        "plugin": plugin,
        "changelog_top": changelog_top,
        "changelog_prev": changelog_prev,
        "latest_tag": latest_tag,
    }


def check(plugin, changelog_top, changelog_prev, latest_tag) -> list:
    """Drift strings across the 3 surfaces (empty list = in sync)."""
    drift = []

    if plugin != changelog_top:
        drift.append(f"plugin.json version {plugin} != CHANGELOG top released {changelog_top}")

    if latest_tag is not None:
        tag_version = latest_tag[1:] if latest_tag.startswith("v") else latest_tag
        if tag_version not in (plugin, changelog_prev):
            drift.append(
                f"latest tag {latest_tag} matches neither plugin.json {plugin} "
                f"nor previous released {changelog_prev}"
            )

    return drift


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Report plugin/CHANGELOG/git-tag version drift (read-only)."
    )
    ap.add_argument("--repo-root", default=".")
    args = ap.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()

    s = gather(repo_root)
    drift = check(s["plugin"], s["changelog_top"], s["changelog_prev"], s["latest_tag"])

    print(f"plugin.json version:    {s['plugin']} (anchor)")
    print(f"CHANGELOG top released: {'PASS' if s['plugin'] == s['changelog_top'] else 'DRIFT: ' + str(s['changelog_top'])}")
    if s["latest_tag"] is None:
        print("latest git tag:         SKIP (no v* tags found)")
    else:
        tag_ok = not any(d.startswith("latest tag") for d in drift)
        print(f"latest git tag:         {'PASS' if tag_ok else 'DRIFT: ' + s['latest_tag']}")

    if drift:
        print("\nDrift detected:")
        for d in drift:
            print(f"  - {d}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
