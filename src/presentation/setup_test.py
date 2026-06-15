import re
from collections.abc import AsyncIterator
from pathlib import Path

from src.presentation.test_support import started_test_client

from src.app import build_app
from src.config import AppConfig
from src.models import LlmMessage
from src.service.response_service import StreamEvent


class FakeResponder:
    """setup routeテスト用の空 responder。"""

    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        """このテストでは応答本文を生成しない。"""
        _ = (messages, assistant)
        events: list[StreamEvent] = []
        for event in events:
            yield event


def test_initial_admin_setup_form_is_available_without_admin(
    tmp_path: Path,
) -> None:
    # 観点: 管理者がいない状態では未ログインで初回管理者作成画面を表示できること。
    # 目的: 起動時自動作成ではなくユーザー主導セットアップへ入れるHTTP入口を固定する。
    client = started_test_client(build_app(_config(tmp_path), responder=FakeResponder()))

    response = client.get("/setup/admin")

    assert response.status_code == 200
    assert 'name="_csrf_token"' in response.text
    assert 'action="/setup/admin"' in response.text


def test_initial_admin_setup_creates_admin_and_redirects_to_login(
    tmp_path: Path,
) -> None:
    # 観点: 初回管理者作成POSTが管理者を作成しログイン画面へ戻すこと。
    # 目的: routeがフォーム入力をusecaseへ渡すだけで初回セットアップを完了できる契約を固定する。
    client = started_test_client(build_app(_config(tmp_path), responder=FakeResponder()))
    page = client.get("/setup/admin")

    response = client.post(
        "/setup/admin",
        data={
            "login_name": "owner",
            "password": "ownerpass",
            "_csrf_token": _csrf_token(page.text),
        },
        follow_redirects=False,
    )
    login_token = _csrf_token(client.get("/login").text)
    login_response = client.post(
        "/login",
        data={
            "login_name": "owner",
            "password": "ownerpass",
            "_csrf_token": login_token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert login_response.status_code == 303


def test_initial_admin_setup_is_closed_after_admin_exists(tmp_path: Path) -> None:
    # 観点: 管理者作成後は初回管理者作成画面へ再アクセスできないこと。
    # 目的: 未ログイン導線から管理者を追加作成できないHTTP境界を固定する。
    client = started_test_client(build_app(_config(tmp_path), responder=FakeResponder()))
    page = client.get("/setup/admin")
    client.post(
        "/setup/admin",
        data={
            "login_name": "owner",
            "password": "ownerpass",
            "_csrf_token": _csrf_token(page.text),
        },
        follow_redirects=False,
    )

    response = client.get("/setup/admin", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def _config(tmp_path: Path) -> AppConfig:
    """setup routeテスト用のAppConfigを返す。"""
    return AppConfig(
        db_path=tmp_path / "chat.sqlite",
        data_dir=tmp_path,
        uploads_dir=tmp_path / "uploads",
        session_secret="test-secret",
        password_pepper="test-pepper",
    )


def _csrf_token(html: str) -> str:
    """HTML内のCSRF hidden値を取り出す。"""
    match = re.search(r'name="_csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)
