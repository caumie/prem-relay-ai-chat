import re
from collections.abc import AsyncIterator
from pathlib import Path

from src.presentation.test_support import started_test_client

from src.app import build_app
from src.config import AppConfig
from src.models import LlmMessage
from src.service.response_service import StreamEvent


class FakeResponder:
    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent("delta", delta="ok")


def test_login_form_includes_csrf_token(tmp_path: Path) -> None:
    # 観点: HTML入口でCSRFトークンがフォームへ返却されること。
    # 目的: POST前にブラウザがhidden tokenを取得できる契約を固定する。
    client = started_test_client(build_app(_config(tmp_path), responder=FakeResponder()))

    response = client.get("/login")

    assert response.status_code == 200
    assert 'name="_csrf_token"' in response.text
    assert _csrf_token(response.text)


def test_login_rejects_post_without_csrf_token(tmp_path: Path) -> None:
    # 観点: 明示的に守るPOSTはCSRFトークンなしで拒否されること。
    # 目的: dependencyによる検証がauth routeへ適用されていることを保証する。
    client = started_test_client(build_app(_config(tmp_path), responder=FakeResponder()))
    client.get("/login")

    response = client.post(
        "/login",
        data={"login_name": "admin", "password": "adminpass"},
        follow_redirects=False,
    )

    assert response.status_code == 403


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        db_path=tmp_path / "chat.sqlite",
        data_dir=tmp_path,
        uploads_dir=tmp_path / "uploads",
        session_secret="test-secret",
        password_pepper="test-pepper",
    )


def _csrf_token(html: str) -> str:
    match = re.search(r'name="_csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)
