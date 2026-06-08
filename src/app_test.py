"""FastAPIアプリ生成時の依存配線と起動初期化を検証する。"""

from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from starlette.routing import Mount, Route

from src.app import build_app
from src.config import AppConfig
from src.infrastructure import AuthRepository, Database
from src.service.response_service import ResponseService
from src.models import LlmMessage
from src.service.response_service import StreamEvent


class FakeResponder:
    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        events: list[StreamEvent] = []
        for event in events:
            yield event


def _route_paths(routes: Sequence[object]) -> set[str]:
    return {route.path for route in routes if isinstance(route, Route | Mount)}


def test_build_app_wires_runtime_dependencies(tmp_path: Path) -> None:
    # 観点: build_appが設定、DB、responder、response_serviceをapp.stateへ配線すること。
    # 目的: app層が各層の具体インスタンス生成とroute登録だけを担う境界を固定する。
    responder = FakeResponder()
    config = _config(tmp_path)

    app = build_app(config, responder=responder)

    assert app.state.config is config
    assert isinstance(app.state.database, Database)
    assert app.state.responder is responder
    assert isinstance(app.state.response_service, ResponseService)
    assert _route_paths(app.routes) >= {
        "/chat",
        "/login",
        "/static",
        "/assets",
    }


def test_build_app_initializes_database_and_bootstrap_admin(tmp_path: Path) -> None:
    # 観点: build_app実行時にDB初期化と初期管理者作成が行われること。
    # 目的: 起動時初期化をusecase詳細ではなくapp配線責務として固定する。
    app = build_app(_config(tmp_path))

    with app.state.database.connect() as conn:
        user = AuthRepository(conn).get_by_login_name("admin")

    assert user is not None
    assert user.is_admin is True


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        db_path=tmp_path / "chat.sqlite",
        data_dir=tmp_path,
        uploads_dir=tmp_path / "uploads",
        session_secret="test-secret",
    )
