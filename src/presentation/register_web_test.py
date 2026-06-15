"""presentation package入口のroute登録責務を検証する。"""

from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from src.presentation.test_support import started_test_client
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Route

from src.infrastructure import Database
from src.models import LlmMessage
from src.presentation import register_web_routes
from src.presentation.runtime import init_presentation_runtime
from src.service.response_service import StreamEvent
from src.config import AppConfig
from src.usecase.runtime import init_usecase_runtime


class FakeResponder:
    """presentation 登録テスト用の空 responder。"""

    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        """このテストでは応答本文を生成しない。"""
        _ = (messages, assistant)
        events: list[StreamEvent] = []
        for event in events:
            yield event


def test_register_web_routes_registers_routes_and_auth_dependencies(
    tmp_path: Path,
) -> None:
    # 観点: presentation package入口だけで個別router登録と依存配線が完結すること。
    # 目的: app層がpresentation内部の分割やdependency構成を知らずにroute登録できる境界を固定する。
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()
    init_usecase_runtime(
        config=AppConfig(
            db_path=tmp_path / "chat.sqlite",
            data_dir=tmp_path,
            uploads_dir=tmp_path / "uploads",
            session_secret="test-secret",
            password_pepper="test-pepper",
        ),
        responder=FakeResponder(),
    )
    init_presentation_runtime(templates=Jinja2Templates(directory="src/templates"))

    register_web_routes(app)

    paths = _route_paths(app.routes)
    response = started_test_client(app, follow_redirects=False).get("/chat")

    assert {"/login", "/setup/admin", "/chat", "/assistants", "/admin/users"} <= paths
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def _route_paths(routes: Sequence[object]) -> set[str]:
    """FastAPI route一覧からpathだけを取り出す。"""
    return {route.path for route in routes if isinstance(route, Route)}
