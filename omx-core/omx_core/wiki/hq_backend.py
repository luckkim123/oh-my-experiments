"""The sole OMX boundary to the hq post store.

The wiki used to parse and write its own frontmatter beside hq's.  That split
made an anchored store's empty legacy wiki directory look like an empty
knowledge base.  Keep all post parsing in hq instead: this module only shapes
its JSON for OMX callers and makes failures loud.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from omx_core.omx_paths import OmxError

HQ_TIMEOUT_S = 10
# These mirror hq's own `post.STATUSES`/`CONFIDENCES`/`TOPICS`. They are copied
# rather than imported because hq ships in a different plugin, and they carry
# `"none"` for the same reason hq does: it is the store's explicit-absence
# sentinel, not a missing value. Leaving it out here made the two sets disagree
# about one schema -- `write_knowledge(status="none")` raised while `hq post
# --status none` is the documented default -- which is the class of split this
# whole migration exists to close. `ACTIONABLE_STATUSES` is the subset callers
# enumerate a backlog with; `"none"` is deliberately not in it.
STATUSES = ("none", "needs-experiment", "needs-apply-before-retrain", "resolved")
ACTIONABLE_STATUSES = ("needs-experiment", "needs-apply-before-retrain", "resolved")
BLOCKING_STATUSES = frozenset({"needs-apply-before-retrain"})
CATEGORIES = frozenset({"architecture", "decision", "pattern", "debugging",
                        "environment", "session-log", "reference", "convention"})
CONFIDENCES = ("high", "medium", "low", "none")
_SUBJECT_STRIP = re.compile(r"[^\w]+", re.UNICODE)
_UPDATE_HEADING = re.compile(r"^## Update \([^)]+\)\n\n", re.MULTILINE)


class HqUnavailable(OmxError):
    """hq cannot answer; this is distinct from a query with no matching posts."""


def title_to_subject(title: str) -> str:
    """Title -> stable merge key without hq's ASCII-only ``_slugify``.

    hq's helper drops Korean-only titles, merging them all into the empty
    subject chain; this store's titles are predominantly Korean (measured).
    """
    subject = _SUBJECT_STRIP.sub("-", title.strip().lower()).strip("-")
    if not subject:
        raise OmxError(f"cannot derive a subject from title {title!r}")
    return subject[:80].strip("-")


def _hq(root, args: tuple[str, ...], *, stdin: str | None = None) -> dict:
    try:
        proc = subprocess.run(
            ["hq", "--anchor", str(root), "--json", *args], input=stdin,
            capture_output=True, text=True, timeout=HQ_TIMEOUT_S, check=False)
    except FileNotFoundError as exc:
        raise HqUnavailable("hq not on PATH (ships with oh-my-orchestrator)") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise HqUnavailable(f"hq invocation failed: {type(exc).__name__}: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip() or "no diagnostic"
        raise HqUnavailable(f"hq exited {proc.returncode}: {detail}")
    try:
        data = json.loads(proc.stdout)
    except (TypeError, ValueError) as exc:
        raise HqUnavailable(f"hq returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise HqUnavailable("hq returned an unexpected JSON shape")
    return data


def hq_json(root, *args: str) -> dict:
    """Run ``hq --anchor <root> --json`` for a read; never turn failure into empty."""
    return _hq(root, tuple(args))


def hq_run(root, *args: str, stdin: str | None = None) -> dict:
    """Run an hq mutation with the same loud failure contract as ``hq_json``."""
    return _hq(root, tuple(args), stdin=stdin)


def is_git_anchor(root) -> bool:
    """Whether ``root`` is inside a git worktree, without shelling out."""
    here = Path(root).resolve()
    return any((parent / ".git").exists() for parent in (here, *here.parents))


def _norm_slug(slug: str) -> str:
    """Post ids are canonical ``category/NNN`` strings, never wiki ``.md`` names."""
    return slug.removesuffix(".md")


def find_head(root, subject: str) -> dict | None:
    """Return hq's unique canonical head for ``subject`` or loudly reject ambiguity."""
    result = hq_json(root, "query", "--subject", subject)
    if result.get("ambiguous"):
        raise OmxError(f"hq subject {subject!r} has multiple heads")
    canonical = result.get("canonical")
    if canonical is not None and not isinstance(canonical, dict):
        raise HqUnavailable("hq query --subject returned an invalid canonical post")
    return canonical


def read_post(root, post_id: str) -> dict | None:
    """Read one post through hq; an absent id is a normal, explicit absence.

    The body comes from hq's `query --post-id` JSON, not from opening the file.
    The first cut here did open it and re-split the header on its own line
    rules, which is precisely the second parser this whole migration exists to
    delete: two readers of one format drift, and every defect this plan has
    found across four rounds was two readers of one thing disagreeing. hq now
    carries `body` on the single-post path (omo 0.17.0) so nothing here has to
    know what a frontmatter bullet looks like.
    """
    result = hq_json(root, "query", "--post-id", _norm_slug(post_id))
    post = result.get("post")
    if post is not None and not isinstance(post, dict):
        raise HqUnavailable("hq query --post-id returned an invalid post")
    if post is None:
        return None
    if "body" not in post:
        raise HqUnavailable(
            "hq query --post-id returned no body -- this needs oh-my-orchestrator "
            ">= 0.17.0; an older hq on PATH would silently look like an empty post")
    return post


def _summary(content: str) -> str:
    return next((line.strip() for line in content.splitlines() if line.strip()), "")[:120]


def _body_blocks(body: str) -> list[str]:
    """Return hq post body chunks without interpreting its metadata header.

    Split on the `---` separator FIRST, then strip each part's `## Update (ts)`
    heading -- which is what the retired `ingest._blocks` did, and skipping the
    separator broke the duplicate guard asymmetrically: splitting only on the
    heading leaves the trailing `---` glued to the first block, so re-adding a
    page's ORIGINAL content never matched and appended a second copy, while
    re-adding a later update matched fine. The timestamp differs on every
    append, so it is removed before comparing.
    """
    blocks = []
    for part in body.split("\n---\n"):
        blocks.append(" ".join(_UPDATE_HEADING.sub("", part).split()))
    return blocks


def write_knowledge(root, *, now: str, title: str, content: str, tags: list[str],
                    category: str, confidence: str, status: str | None = None,
                    quality_score: int | None = None,
                    quality_reasons: list | tuple = ()) -> dict:
    """Create or append one mutable-subject post, retaining wiki's duplicate guard."""
    if category not in CATEGORIES:
        raise OmxError(f"category {category!r} not in {sorted(CATEGORIES)}")
    if confidence not in CONFIDENCES:
        raise OmxError(f"confidence {confidence!r} not in {list(CONFIDENCES)}")
    if status is not None and status not in STATUSES:
        raise OmxError(f"status {status!r} not in {list(STATUSES)}")
    if not title.strip():
        raise OmxError("wiki page title must be non-empty")
    subject = title_to_subject(title)
    existing = find_head(root, subject)
    if existing is None:
        result = hq_run(
            root, "post", "--category", "finding", "--topic", category,
            "--subject", subject, "--title", title, "--author", "omx",
            "--keywords", ",".join(dict.fromkeys(tags)), "--confidence", confidence,
            "--status", status or "none", "--summary", _summary(content), "--body-file", "-",
            stdin=content)
        return {"action": "created", "slug": result["id"],
                "quality_score": quality_score, "quality_reasons": list(quality_reasons)}

    existing = read_post(root, existing["id"])
    if existing is None:  # post disappeared after the canonical-head lookup
        raise HqUnavailable("hq canonical post disappeared before it could be edited")
    fields = existing.get("fields") or {}
    body = str(existing.get("body") or "")
    duplicate = " ".join(content.split()) in _body_blocks(body)
    post_id = existing.get("id")
    if not isinstance(post_id, str):
        raise HqUnavailable("hq canonical post has no id")
    if duplicate:
        return {"action": "unchanged", "slug": post_id,
                "quality_score": quality_score, "quality_reasons": list(quality_reasons)}
    # The trailing newline is load-bearing: hq appends `## Comments` straight
    # after the body it is given, and `edit --reason` always writes a comment,
    # so a body ending mid-line puts a markdown heading on the same block as
    # prose. Measured on a copy of the live 125-post store.
    merged = body.rstrip() + f"\n\n---\n\n## Update ({now})\n\n{content.rstrip()}\n"
    if is_git_anchor(root):
        args = ["edit", post_id, "--author", "omx", "--reason", "wiki add append-merge",
                "--body-file", "-"]
        if status is not None:
            args += ["--status", status]
        result = hq_run(root, *args, stdin=merged)
        slug = result.get("id", post_id)
    else:
        result = hq_run(
            root, "post", "--category", "finding", "--topic", category,
            "--subject", subject, "--supersedes", post_id, "--title", title,
            "--author", "omx", "--keywords", ",".join(dict.fromkeys(tags)),
            "--confidence", confidence, "--status", status or fields.get("status", "none"),
            "--summary", _summary(content), "--body-file", "-", stdin=merged)
        slug = result["id"]
    return {"action": "updated", "slug": slug,
            "quality_score": quality_score, "quality_reasons": list(quality_reasons)}
