import re
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.presentation.test_support import (
    usecase_runtime_for,
    started_test_client,
)

from src.app import build_app
from src.config import AppConfig
from src.models import LlmMessage, User
from src.service.response_service import StreamEvent
from src.usecase.admin_user import AdminUserUsecaseContext, create_user


class FakeResponder:
    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent("delta", delta="ok")


def test_admin_user_create_route_redirects_and_lists_user(tmp_path: Path) -> None:
    # 観点: 管理者のユーザー作成POSTがCSRF付きフォームから実行され一覧へ戻ること。
    # 目的: user作成の業務詳細ではなくHTTP入口の配線契約だけを固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    client = started_test_client(app)
    _login(client)
    page = client.get("/admin/users")

    response = client.post(
        "/admin/users",
        data={
            "login_name": "user1",
            "password": "pass123",
            "_csrf_token": _csrf_token(page.text),
        },
        follow_redirects=False,
    )
    listed = client.get("/admin/users")

    assert response.status_code == 303
    assert "user1" in listed.text


def test_admin_user_update_route_redirects_and_lists_updated_user(
    tmp_path: Path,
) -> None:
    # 観点: 管理者のユーザー編集POSTが対象ユーザーを更新して一覧へ戻ること。
    # 目的: update_user usecaseへのHTTPフォーム配線を固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    user = _create_user(app, "user1", "pass123")
    client = started_test_client(app)
    _login(client)
    edit_page = client.get(f"/admin/users/{user.id}/edit")

    response = client.post(
        f"/admin/users/{user.id}/edit",
        data={
            "login_name": "user1-updated",
            "password": "pass456",
            "is_admin": "on",
            "_csrf_token": _csrf_token(edit_page.text),
        },
        follow_redirects=False,
    )
    listed = client.get("/admin/users")

    assert response.status_code == 303
    assert "user1-updated" in listed.text


def test_admin_user_suspend_route_redirects_and_exposes_delete_action(
    tmp_path: Path,
) -> None:
    # 観点: 管理者のユーザー休止POSTが対象を休止状態にし削除操作を表示すること。
    # 目的: suspend_user usecaseへのHTTPフォーム配線を固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    user = _create_user(app, "user1", "pass123")
    client = started_test_client(app)
    _login(client)
    page = client.get("/admin/users")

    response = client.post(
        f"/admin/users/{user.id}/suspend",
        data={"_csrf_token": _csrf_token(page.text)},
        follow_redirects=False,
    )
    edit_page = client.get(f"/admin/users/{user.id}/edit")

    assert response.status_code == 303
    assert f"/admin/users/{user.id}/delete" in edit_page.text


def test_admin_user_delete_route_redirects_and_removes_user_from_list(
    tmp_path: Path,
) -> None:
    # 観点: 休止済みユーザーの削除POSTが対象を一覧から除外すること。
    # 目的: delete_user usecaseへのHTTPフォーム配線を固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    user = _create_user(app, "user1", "pass123")
    client = started_test_client(app)
    _login(client)
    page = client.get("/admin/users")
    client.post(
        f"/admin/users/{user.id}/suspend",
        data={"_csrf_token": _csrf_token(page.text)},
        follow_redirects=False,
    )
    delete_page = client.get(f"/admin/users/{user.id}/edit")

    response = client.post(
        f"/admin/users/{user.id}/delete",
        data={"_csrf_token": _csrf_token(delete_page.text)},
        follow_redirects=False,
    )
    listed = client.get("/admin/users")

    assert response.status_code == 303
    assert "user1" not in listed.text


def test_admin_user_routes_reject_non_admin_user(tmp_path: Path) -> None:
    # 観点: 一般ユーザーは管理画面へ入れないこと。
    # 目的: 管理機能のHTTP境界に管理者権限チェックがあることを固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    _create_user(app, "user1", "pass123")
    client = started_test_client(app)
    _login(client, "user1", "pass123")

    response = client.get("/admin/users")

    assert response.status_code == 403


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        db_path=tmp_path / "chat.sqlite",
        data_dir=tmp_path,
        uploads_dir=tmp_path / "uploads",
        session_secret="test-secret",
        password_pepper="test-pepper",
    )


def _login(client: TestClient, login_name: str = "admin", password: str = "adminpass") -> None:
    if login_name == "admin" and password == "adminpass":
        _ensure_initial_admin(client)
    login_token = _csrf_token(client.get("/login").text)
    response = client.post(
        "/login",
        data={
            "login_name": login_name,
            "password": password,
            "_csrf_token": login_token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _ensure_initial_admin(client: TestClient) -> None:
    """初回セットアップ画面から既定管理者を用意する。"""
    page = client.get("/setup/admin", follow_redirects=False)
    if page.status_code != 200:
        return
    response = client.post(
        "/setup/admin",
        data={
            "login_name": "admin",
            "password": "adminpass",
            "_csrf_token": _csrf_token(page.text),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _create_user(app: FastAPI, login_name: str, password: str) -> User:
    """admin user作成ユースケースでテストユーザーを作る。

    Args:
        app: build_appで生成したFastAPIアプリ。
        login_name: 作成するログイン名。
        password: 作成するユーザーの平文パスワード。

    Returns:
        作成済みユーザー。

    routeテストがユーザー保存形式を直接持たずにログイン前提を作れるようにする。
    """
    return create_user(
        login_name=login_name,
        password=password,
        is_admin=False,
        context=AdminUserUsecaseContext(
            database=usecase_runtime_for(app).database,
            password_pepper="test-pepper",
            attachment_storage=usecase_runtime_for(app).attachment_storage,
        ),
    )


def _csrf_token(html: str) -> str:
    match = re.search(r'name="_csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)
