import pytest

from pathlib import Path


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_hq_shellout(monkeypatch):
    """`enumerate_pages` 는 이제 `hq` 를 shell out 해 post 스토어를 읽는다.

    그대로 두면 테스트 결과가 "이 머신에 hq 가 깔렸나"와 "tmp_path 위쪽에 앵커가
    있나"에 달린다 — 오늘 claudebase 에서 고친 것과 같은 비-hermetic 함정이다.
    기본값을 "post 소스 없음"으로 고정하고, 그 경로를 검사하는 테스트는 자기가
    monkeypatch 로 켠다(이 fixture 뒤에 실행되므로 이긴다).
    """
    from omx_core.wiki import query as _q

    monkeypatch.setattr(
        _q, "_post_store_pages",
        lambda paths, status: ([], {"ok": True, "count": 0, "error": None}))


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
