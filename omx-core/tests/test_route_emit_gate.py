"""route_emit relevance-gate tests (wave-17, OMX_ROUTE_GATE, default off).

Isomorphic to oms's test_scholar_route_emit.py relevance-gate suite (§7.1/§7.2
of the design spec) and to omd/omp's own gate suites. Default OFF must be
indistinguishable from today's route_emit for ANY payload. Loads hooks/handlers.py
directly (same pattern as test_hook_handlers_r3.py / test_hook_backlog.py) --
route_emit is a plain function here, not a subprocess-invoked script."""
import importlib.util
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HANDLERS_PATH = REPO / "hooks" / "handlers.py"


def _load_handlers():
    spec = importlib.util.spec_from_file_location("omx_hook_handlers_gate", str(HANDLERS_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _no_env(monkeypatch):
    monkeypatch.delenv("OMX_ROUTE_GATE", raising=False)


def test_gate_default_off_injects_even_for_irrelevant_prompt(monkeypatch):
    """기본값(env 미설정) = off. 무관 프롬프트도 오늘처럼 무조건 주입."""
    _no_env(monkeypatch)
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_fetch_open_backlog", lambda p: "")
    out = mod.route_emit({"prompt": "hello", "cwd": "/tmp/nonexistent-omx-probe"})
    assert "STAGE(exp)" in out["hookSpecificOutput"]["additionalContext"]


def test_gate_off_mode_injects_always(monkeypatch):
    """OMX_ROUTE_GATE=off 명시해도 동일 — 게이트 코드 전체 우회."""
    monkeypatch.setenv("OMX_ROUTE_GATE", "off")
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_fetch_open_backlog", lambda p: "")
    out = mod.route_emit({"prompt": "random unrelated text"})
    assert "STAGE(exp)" in out["hookSpecificOutput"]["additionalContext"]


def test_gate_on_non_domain_prompt_is_silent(monkeypatch, tmp_path):
    """on + marker 없는 cwd + 무관 프롬프트 → None(주입 안 함)."""
    monkeypatch.setenv("OMX_ROUTE_GATE", "on")
    mod = _load_handlers()
    assert mod.route_emit({"prompt": "hello", "cwd": str(tmp_path)}) is None


def test_gate_on_word_boundary_no_false_positive(monkeypatch, tmp_path):
    """on + 부분문자열 오탐 금지 — "eval" 이 "evaluate" 안에서 발동하면 안 된다."""
    monkeypatch.setenv("OMX_ROUTE_GATE", "on")
    mod = _load_handlers()
    out = mod.route_emit({"prompt": "please evaluate this approach", "cwd": str(tmp_path)})
    assert out is None


def test_gate_on_missing_prompt_key_injects(monkeypatch, tmp_path):
    """on + prompt 키 자체가 없으면 fail-toward-inject — 전체 CHECKPOINT."""
    monkeypatch.setenv("OMX_ROUTE_GATE", "on")
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_fetch_open_backlog", lambda p: "")
    out = mod.route_emit({"cwd": str(tmp_path)})
    assert "STAGE(exp)" in out["hookSpecificOutput"]["additionalContext"]


def test_gate_on_bad_payload_fail_open(monkeypatch):
    """on + payload 가 dict 가 아니면(malformed) → prompt/cwd 모두 None 으로
    degrade → fail-toward-inject (run_hook.py 의 json.load 가 object 가 아닌
    JSON — 리스트 등 — 을 파싱했을 때의 방어)."""
    monkeypatch.setenv("OMX_ROUTE_GATE", "on")
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_fetch_open_backlog", lambda p: "")
    out = mod.route_emit([1, 2, 3])
    assert "STAGE(exp)" in out["hookSpecificOutput"]["additionalContext"]


def test_gate_on_marker_present_forces_inject(monkeypatch, tmp_path):
    """on + .omx/ 존재 → 무관 프롬프트여도 주입 (marker OR keyword 의 marker 다리)."""
    monkeypatch.setenv("OMX_ROUTE_GATE", "on")
    (tmp_path / ".omx").mkdir()
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_fetch_open_backlog", lambda p: "")
    out = mod.route_emit({"prompt": "hello", "cwd": str(tmp_path)})
    assert "STAGE(exp)" in out["hookSpecificOutput"]["additionalContext"]


def test_gate_on_keyword_only_injects_without_marker(monkeypatch, tmp_path):
    """on + marker 없는 cwd + 도메인 키워드("exp-analyze 돌려줘") → 주입."""
    monkeypatch.setenv("OMX_ROUTE_GATE", "on")
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_fetch_open_backlog", lambda p: "")
    out = mod.route_emit({"prompt": "exp-analyze 돌려줘", "cwd": str(tmp_path)})
    assert "STAGE(exp)" in out["hookSpecificOutput"]["additionalContext"]


def test_gate_on_excluded_polyseme_is_silent(monkeypatch, tmp_path):
    """on + marker 없는 cwd + 다의어 단독("run the tests") → 침묵 (제외 규칙 확인)."""
    monkeypatch.setenv("OMX_ROUTE_GATE", "on")
    mod = _load_handlers()
    assert mod.route_emit({"prompt": "run the tests", "cwd": str(tmp_path)}) is None


def test_gate_observe_mode_injects_and_logs(monkeypatch, tmp_path, capsys):
    """observe + 무관 프롬프트 → 여전히 주입(byte-identity 유지) + would-suppress 로그 1줄."""
    monkeypatch.setenv("OMX_ROUTE_GATE", "observe")
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_fetch_open_backlog", lambda p: "")
    out = mod.route_emit({"prompt": "hello", "cwd": str(tmp_path)})
    assert "STAGE(exp)" in out["hookSpecificOutput"]["additionalContext"]
    logged = json.loads(capsys.readouterr().err.strip())
    assert logged["decision"] == "would-suppress"


def test_gate_on_golden_positive_path_byte_identical(monkeypatch, tmp_path):
    """§4 HARD REQUIREMENT fixture (a): keyword-only cwd (checkpoint 단독,
    backlog mock 고정) — gate=on 의 true-positive 출력이 off(=오늘)와
    byte-for-byte 동일해야 한다."""
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_fetch_open_backlog", lambda p: "")
    payload = {"prompt": "exp-analyze 돌려줘", "cwd": str(tmp_path)}

    monkeypatch.setenv("OMX_ROUTE_GATE", "off")
    off_out = mod.route_emit(payload)
    monkeypatch.setenv("OMX_ROUTE_GATE", "on")
    on_out = mod.route_emit(payload)
    assert on_out == off_out


def test_gate_on_golden_positive_path_byte_identical_with_marker_and_backlog(monkeypatch, tmp_path):
    """§4 HARD REQUIREMENT fixture (b): omx-root 있는 cwd (checkpoint+backlog
    조립, backlog mock 고정) — gate=on 의 true-positive 출력이 off(=오늘)와
    byte-for-byte 동일해야 한다(조립 방식 불변)."""
    (tmp_path / ".omx").mkdir()
    mod = _load_handlers()
    monkeypatch.setattr(mod, "_fetch_open_backlog", lambda p: "<omx-open-backlog>X</omx-open-backlog>")
    payload = {"prompt": "hello", "cwd": str(tmp_path)}

    monkeypatch.setenv("OMX_ROUTE_GATE", "off")
    off_out = mod.route_emit(payload)
    monkeypatch.setenv("OMX_ROUTE_GATE", "on")
    on_out = mod.route_emit(payload)
    assert on_out == off_out
    assert on_out["hookSpecificOutput"]["additionalContext"].endswith(
        "<omx-open-backlog>X</omx-open-backlog>")


def test_marker_probe_no_subprocess(monkeypatch, tmp_path):
    """checkpoint-gate 마커 프로브는 subprocess 를 쓰지 않는다 (pathlib .omx/
    프로브만 -- _fetch_open_backlog 의 resolve_omx_root 래더와 달리 git 을
    shell 하지 않는다). 스펙 3.3/triage 요구사항: checkpoint gate 에 subprocess
    금지."""
    (tmp_path / ".omx").mkdir()
    mod = _load_handlers()

    def boom(*a, **k):
        raise AssertionError("marker probe must not shell out")
    monkeypatch.setattr(subprocess, "run", boom)
    assert mod.is_exp_related("irrelevant prompt here", str(tmp_path)) is True


def test_gate_stdlib_only():
    """게이트 추가 후에도 stdlib only 유지 (회귀) -- handlers.py 는 subprocess 를
    이미 _fetch_open_backlog 에서 쓰지만(기존), 그 외 신규 코드는 stdlib 만."""
    src = HANDLERS_PATH.read_text()
    assert "import requests" not in src and "import yaml" not in src
