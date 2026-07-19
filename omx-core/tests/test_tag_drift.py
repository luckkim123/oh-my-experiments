"""Tag-drift guard, ported from oh-my-scholar's test_version_sync.py tag-drift
semantics: the latest reachable `v*` tag may be at most ONE version behind the
declared plugin.json version (release-in-progress OK); TWO+ behind is drift;
no tags at all skips the surface (young repo / shallow clone without tags).

`check()`/`gather()` live in scripts/tag_drift.py, importable without
installing omx-core. `test_live_repo_tags_agree` is the live lock: it fails
for real if this repo's own tags fall behind — that is correct guard
behavior, not a bug in the test. CI needs `actions/checkout@v4` with
`fetch-tags: true` (see .github/workflows/tag-guard.yml); the default
checkout does not fetch tags, which is exactly how this drift went
undetected upstream.
"""
import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "tag_drift.py"
spec = importlib.util.spec_from_file_location("tag_drift", SCRIPT)
td = importlib.util.module_from_spec(spec)
spec.loader.exec_module(td)


def test_in_sync_passes():
    assert td.check("0.8.0", "0.8.0", "0.7.0", "v0.7.0") == []  # pre-tag window
    assert td.check("0.8.0", "0.8.0", "0.7.0", "v0.8.0") == []  # post-tag


def test_tag_one_behind_is_release_in_progress():
    assert td.check("0.8.0", "0.8.0", "0.7.0", "v0.7.0") == []


def test_tag_two_behind_is_drift():
    drift = td.check("0.8.0", "0.8.0", "0.7.0", "v0.6.0")
    assert drift
    assert any("v0.6.0" in d for d in drift)


def test_tag_ahead_is_drift():
    drift = td.check("0.8.0", "0.8.0", "0.7.0", "v0.9.0")
    assert drift
    assert any("v0.9.0" in d for d in drift)


def test_no_tags_skips_tag_surface():
    assert td.check("0.8.0", "0.8.0", "0.7.0", None) == []


def test_plugin_changelog_drift_detected():
    drift = td.check("0.8.0", "0.7.0", "0.6.0", None)
    assert drift
    assert any("0.8.0" in d and "0.7.0" in d for d in drift)


def test_changelog_parser_skips_unreleased():
    text = (
        "# Changelog\n\n## [Unreleased]\n\n## [0.8.0] - 2026-07-20\n\n"
        "## [0.7.0] - 2026-07-13\n"
    )
    p = REPO / "CHANGELOG.md"
    real = td.parse_changelog(p)
    assert "Unreleased" not in real[0] if real else True
    # exercise the regex directly against inline text too (no tmp file needed)
    versions = [m.group(1) for line in text.splitlines() if (m := td.CHANGELOG_RE.match(line))]
    assert versions[0] == "0.8.0"


def test_tag_parse_is_exact_match():
    tags = ["v0.7.0", "v0.7.0-rc1", "x0.9.9", "v10.0"]
    assert td.parse_tags(tags) == "v0.7.0"


def test_live_repo_tags_agree():
    """Live lock against this repo's real state. A genuine failure here means
    the latest pushed v-tag has fallen 2+ versions behind plugin.json/CHANGELOG
    — the exact drift this guard exists to catch, not a test bug."""
    s = td.gather(REPO)
    drift = td.check(s["plugin"], s["changelog_top"], s["changelog_prev"], s["latest_tag"])
    assert not drift, "; ".join(drift)


def test_cli_read_only():
    src = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r'open\([^)]*["\']w', src)
    assert "write_text(" not in src
