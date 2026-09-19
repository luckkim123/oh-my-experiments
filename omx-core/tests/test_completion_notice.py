"""Tests for the `completion_notice` SessionStart handler (Task 6, run-completion-gate
round). One-time opt-in nudge: a project with an omx layer but no `run_completion`
contract gets told the block exists; everything else (contract present, no omx layer,
an unreadable/malformed profile) stays silent. Loads hooks/handlers.py directly, same
pattern as test_hook_handlers_r3.py's compact_breadcrumb section."""
import importlib.util
from pathlib import Path

import yaml
from omx_core.profile import default_metrics

REPO = Path(__file__).resolve().parents[2]
HANDLERS_PATH = REPO / "hooks" / "handlers.py"


def _load_handlers():
    spec = importlib.util.spec_from_file_location(
        "omx_completion_notice_handlers", str(HANDLERS_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _good_block():
    return {
        "runs": "runs/*",
        "finished": "checkpoints/*.pt",
        "required": ["eval/*.json"],
        "how": "python analysis/eval.py static --run {run}",
    }


def _omx_profile(tmp_path, run_completion=None):
    """A legacy `.omx/` layer with a REAL bootstrapped-shaped profile/metrics.yaml
    (default_metrics()) -- the ordinary "valid profile, run_completion key simply
    absent" case this handler exists for, not a synthetic minimal dict (the shape
    a hand-rolled `{"output_root": ...}` fixture would too easily miss)."""
    (tmp_path / ".omx").mkdir()
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    data = default_metrics()
    if run_completion is not None:
        data["run_completion"] = run_completion
    (prof / "metrics.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return tmp_path


def _anchored_omx_profile(tmp_path, run_completion=None):
    """The .hq/-anchored equivalent (store-spec §7 stage 2) -- the same regression
    class compact_breadcrumb's anchored test guards: omx_dir is unconditionally
    legacy, so a getter that ignores has_anchor() silently misses .hq/ content."""
    anchor = tmp_path / ".hq" / ".anchor"
    anchor.parent.mkdir(parents=True)
    anchor.write_text("id: test-anchor\n", encoding="utf-8")
    prof = tmp_path / ".hq" / "config" / "experiments" / "profile"
    prof.mkdir(parents=True)
    data = default_metrics()
    if run_completion is not None:
        data["run_completion"] = run_completion
    (prof / "metrics.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return tmp_path


def test_no_omx_layer_is_silent(tmp_path):
    mod = _load_handlers()
    assert mod.completion_notice({"cwd": str(tmp_path), "source": "startup"}) is None


def test_ignores_sources_other_than_startup_or_resume(tmp_path):
    mod = _load_handlers()
    root = _omx_profile(tmp_path)  # contract absent -- would otherwise fire
    assert mod.completion_notice({"cwd": str(root), "source": "compact"}) is None
    assert mod.completion_notice({"cwd": str(root), "source": "clear"}) is None
    assert mod.completion_notice({"cwd": str(root)}) is None  # source missing entirely


def test_contract_absent_names_run_completion_and_its_file(tmp_path):
    mod = _load_handlers()
    root = _omx_profile(tmp_path)
    out = mod.completion_notice({"cwd": str(root), "source": "startup"})
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    ctx = hso["additionalContext"]
    assert "run_completion" in ctx
    assert "metrics.yaml" in ctx
    # fix-round-1, Finding 2: `omx close-check --help` documents --root/--json/
    # --record and never mentions run_completion or metrics.yaml -- pointing a
    # user there sent them on a trip that doesn't answer the question. No
    # dead-end pointer until a real doc/skill target exists (Task 10).
    assert "close-check" not in ctx
    # Task 10: the dead pointer is replaced, not left absent -- exp-init's
    # SKILL.md now carries the real "Completion contract" section.
    assert "exp-init" in ctx


def test_contract_absent_also_fires_on_resume(tmp_path):
    mod = _load_handlers()
    root = _omx_profile(tmp_path)
    out = mod.completion_notice({"cwd": str(root), "source": "resume"})
    assert out is not None


def test_contract_absent_fires_on_anchored_hq_store_too(tmp_path):
    mod = _load_handlers()
    root = _anchored_omx_profile(tmp_path)
    out = mod.completion_notice({"cwd": str(root), "source": "startup"})
    assert out is not None
    assert "run_completion" in out["hookSpecificOutput"]["additionalContext"]


def test_uses_cwd_not_the_root_ladder_when_a_workspace_marker_sits_above(tmp_path):
    """Ruling 27: the #13 root ladder is walked from cwd upward and can land on
    an ANCESTOR via a .omx-workspace marker file. Reading that ladder-resolved
    root instead of cwd itself would silently check a DIFFERENT project's
    profile than the one whose layer _has_omx_marker just confirmed at cwd --
    here the ancestor has no profile at all, so a ladder-based read would raise,
    get caught by the fail-open except, and wrongly stay silent."""
    mod = _load_handlers()
    (tmp_path / ".omx-workspace").write_text("", encoding="utf-8")  # ladder anchors HERE
    child = tmp_path / "child"
    child.mkdir()
    root = _omx_profile(child)  # contract absent, the layer/profile live at child/.omx
    out = mod.completion_notice({"cwd": str(root), "source": "startup"})
    assert out is not None
    assert "run_completion" in out["hookSpecificOutput"]["additionalContext"]


def test_contract_present_is_silent(tmp_path):
    mod = _load_handlers()
    root = _omx_profile(tmp_path, run_completion=_good_block())
    assert mod.completion_notice({"cwd": str(root), "source": "startup"}) is None


def test_contract_present_is_silent_on_anchored_hq_store_too(tmp_path):
    mod = _load_handlers()
    root = _anchored_omx_profile(tmp_path, run_completion=_good_block())
    assert mod.completion_notice({"cwd": str(root), "source": "startup"}) is None


def test_no_profile_bootstrapped_yet_is_silent(tmp_path):
    """omx layer present (.omx/ marker dir) but no profile/metrics.yaml at all --
    load_profile_metrics raises OmxError('no profile ...'); must fail open, never raise."""
    mod = _load_handlers()
    (tmp_path / ".omx").mkdir()
    assert mod.completion_notice({"cwd": str(tmp_path), "source": "startup"}) is None


def test_malformed_metrics_yaml_is_silent(tmp_path):
    """A metrics.yaml that doesn't parse to a mapping is an internal error, not a
    'contract absent' -- must still fail open, never raise."""
    mod = _load_handlers()
    (tmp_path / ".omx").mkdir()
    prof = tmp_path / ".omx" / "profile"
    prof.mkdir(parents=True)
    (prof / "metrics.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
    assert mod.completion_notice({"cwd": str(tmp_path), "source": "startup"}) is None


def test_garbage_cwd_is_silent():
    mod = _load_handlers()
    assert mod.completion_notice({"cwd": 12345, "source": "startup"}) is None
    assert mod.completion_notice({"source": "startup"}) is None  # cwd missing entirely


def test_registered_in_handlers_table():
    mod = _load_handlers()
    assert mod.HANDLERS["completion_notice"] is mod.completion_notice
