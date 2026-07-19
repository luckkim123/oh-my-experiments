"""#20 (D-R5-2): `omx wiki delete` is a deprecation-as-runtime-redirect stub.

0.1.13 added the passive half (gc-apply help text) after a session concluded
"delete does not exist" from --help alone. The active stub catches the
deprecated call and reconstructs the replacement: always rc 2, a JSON error
naming gc + gc-apply, the caller's --root echoed back, positional slug parsed
(never an argparse 'invalid choice' death), and stdout carrying NO partial
success (INV-2: the stub deletes nothing)."""
import json

from omx_core import cli


def test_wiki_delete_always_rc2(tmp_path, capsys):
    rc = cli.main(["wiki", "delete", "some-slug", "--root", str(tmp_path)])
    assert rc == 2


def test_wiki_delete_emits_json_redirect_on_stderr(tmp_path, capsys):
    rc = cli.main(["wiki", "delete", "some-slug", "--root", str(tmp_path)])
    cap = capsys.readouterr()
    assert rc == 2
    assert cap.out == ""                       # stdout pure — no partial success
    err = json.loads(cap.err.strip())          # the loud-fail message IS JSON
    assert err["error"] == "deprecated"
    assert "INV-2" in err["reason"]
    assert "gc" in err["cli_replacement"] and "gc-apply" in err["cli_replacement"]
    assert str(tmp_path) in err["cli_replacement"]   # caller --root echoed back


def test_wiki_delete_echoes_default_root_when_omitted(capsys):
    rc = cli.main(["wiki", "delete", "some-slug"])
    err = json.loads(capsys.readouterr().err.strip())
    assert rc == 2
    # default root is the #13-ladder resolution (a real dir path), not literal '.'
    assert "--root" in err["cli_replacement"]


def test_wiki_delete_parses_without_positional_slug(capsys):
    # even with no slug the stub must reach the redirect, not argparse-error
    rc = cli.main(["wiki", "delete"])
    err = json.loads(capsys.readouterr().err.strip())
    assert rc == 2 and err["error"] == "deprecated"


def test_wiki_delete_registered_as_real_subcommand():
    # the #25 verb-contract test globs skills for `omx wiki <sub>`; delete must
    # be a genuine registered choice so a doc mention would not be flagged.
    import argparse

    from omx_core.cli import build_parser
    for a in build_parser()._actions:
        if isinstance(a, argparse._SubParsersAction) and "wiki" in a.choices:
            wiki = a.choices["wiki"]
            subs = set()
            for b in wiki._actions:
                if isinstance(b, argparse._SubParsersAction):
                    subs |= set(b.choices)
            assert "delete" in subs
            return
    raise AssertionError("wiki subparser not found")
