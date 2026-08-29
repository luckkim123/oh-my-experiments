import subprocess
from pathlib import Path

import pytest


class _HqStub:
    """A stand-in for `hq_backend`'s `subprocess` NAME, not for the module.

    Patching `hq_backend.subprocess.run` would patch the stdlib module object
    itself -- `import subprocess` hands every module the same object -- so the
    fake also answered `root._git`'s `check_output`, which then called
    `.decode()` on a str and took 130 unrelated tests down with it. Rebinding
    the name inside hq_backend touches nothing else in the process.
    """

    SubprocessError = subprocess.SubprocessError
    TimeoutExpired = subprocess.TimeoutExpired
    CalledProcessError = subprocess.CalledProcessError

    def __init__(self, run):
        self.run = run


def hq_stub(run):
    """The object tests bind to `hq_backend.subprocess`."""
    return _HqStub(run)


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_hq_shellout(monkeypatch):
    """wiki 의 모든 읽기·쓰기는 이제 `hq` 를 shell out 한다 (B4).

    그대로 두면 테스트 결과가 "이 머신에 hq 가 깔렸나"와 "tmp_path 위쪽에 앵커가
    있나"에 달린다 — 오늘 claudebase 에서 고친 것과 같은 비-hermetic 함정이다.
    기본값을 "hq 없음"으로 고정하고, 그 경로를 검사하는 테스트는 자기가
    monkeypatch 로 켠다(이 fixture 뒤에 실행되므로 이긴다).

    B4 이후 패치 지점은 `hq_backend.subprocess` 다. 옛 자리인
    `query._post_store_pages` 만 막으면 `query_wiki`·`write_knowledge` 는 진짜
    `hq` 로 새어나간다 — 막힌 것처럼 보이면서 안 막힌 상태가 제일 나쁘다.
    """
    import subprocess as _sp

    from omx_core.wiki import hq_backend as _hq

    def _refuse(cmd, **kw):
        return _sp.CompletedProcess(
            cmd, 1, stdout="",
            stderr="hermetic test default: no hq on PATH. Opt in with a fake.")

    monkeypatch.setattr(_hq, "subprocess", hq_stub(_refuse))


@pytest.fixture
def live_hq(monkeypatch):
    """Opt back in to the REAL `hq`, or skip.

    The hermetic default above is right for unit tests, but a mock of hq is
    still a second reader of hq's format, and this migration exists because two
    readers drift. A handful of round-trips have to go through the real binary
    or nothing in this suite would catch the drift the mocks cannot see.
    Skipped rather than failed when `hq` is absent: it ships with a different
    plugin, and a machine without it is a supported configuration.
    """
    import shutil

    if shutil.which("hq") is None:
        pytest.skip("hq not on PATH (ships with oh-my-orchestrator)")
    monkeypatch.undo()          # drop the hermetic stub for this test
    monkeypatch.delenv("OMX_ROUTE_GATE", raising=False)


@pytest.fixture(autouse=True)
def _neutral_route_gate(monkeypatch):
    """OMX_ROUTE_GATE 를 개발자 셸에서 물려받지 않는다.

    route_emit 은 게이트가 on 이면 비실험 프롬프트에 None 을 낸다(의도된 동작).
    그 사실을 모르는 테스트가 주입 형태를 단언하면 셸에 이 변수가 켜져 있는
    사람에게서만 5건이 깨진다 — CI 는 초록인데 로컬만 빨간, 재현이 환경에 달린
    실패다. 기본값(off)으로 고정하고, 모드를 검사하는 테스트는 지금처럼
    자기가 monkeypatch.setenv 로 켠다(이 fixture 뒤에 실행되므로 이긴다).
    """
    monkeypatch.delenv("OMX_ROUTE_GATE", raising=False)
