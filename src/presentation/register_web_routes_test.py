"""presentation package入口のroute登録責務を検証する。"""

from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Route

from src.infrastructure import AttachmentStorage, Database
from src.models import LlmMessage
from src.presentation import register_web_routes
from src.service.response_service import ResponseService, StreamEvent
from src.usecase.context import UsecaseContext


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
    storage = AttachmentStorage(tmp_path / "uploads")
    response_service = ResponseService(database=database, responder=FakeResponder())

    register_web_routes(
        app,
        templates=Jinja2Templates(directory="src/templates"),
        usecase_context=UsecaseContext(
            database=database,
            password_pepper="test-secret",
            response_service=response_service,
            uploads_dir=tmp_path / "uploads",
            attachment_storage=storage,
            load_connection_providers=lambda: [],
        ),
        response_service=response_service,
        attachment_storage=storage,
    )

    paths = _route_paths(app.routes)
    response = TestClient(app, follow_redirects=False).get("/chat")

    assert {"/login", "/chat", "/assistants", "/admin/users"} <= paths
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def _route_paths(routes: Sequence[object]) -> set[str]:
    """FastAPI route一覧からpathだけを取り出す。"""
    return {route.path for route in routes if isinstance(route, Route)}
