import re
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi.testclient import TestClient

from src.app import build_app
from src.auth_password import hash_password
from src.config import AppConfig
from src.infrastructure import AuthRepository, Database
from src.models import LlmMessage, User
from src.service.response_service import StreamEvent


class FakeResponder:
    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent("delta", delta="ok")


def test_admin_user_create_route_redirects_and_lists_user(tmp_path: Path) -> None:
    # 観点: 管理者のユーザー作成POSTがCSRF付きフォームから実行され一覧へ戻ること。
    # 目的: user作成の業務詳細ではなくHTTP入口の配線契約だけを固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    client = TestClient(app)
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
    user = _save_user(app.state.database, "user1", "pass123")
    client = TestClient(app)
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
    user = _save_user(app.state.database, "user1", "pass123")
    client = TestClient(app)
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
    user = _save_user(app.state.database, "user1", "pass123")
    client = TestClient(app)
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
    _save_user(app.state.database, "user1", "pass123")
    client = TestClient(app)
    _login(client, "user1", "pass123")

    response = client.get("/admin/users")

    assert response.status_code == 403


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        db_path=tmp_path / "chat.sqlite",
        data_dir=tmp_path,
        uploads_dir=tmp_path / "uploads",
        session_secret="test-secret",
    )


def _login(client: TestClient, login_name: str = "admin", password: str = "adminpass") -> None:
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


def _save_user(database: Database, login_name: str, password: str) -> User:
    with database.connect() as conn:
        user = AuthRepository(conn).save(
            User(id=0, login_name=login_name),
            password_hash=hash_password(password, "test-secret"),
        )
        conn.commit()
        return user


def _csrf_token(html: str) -> str:
    match = re.search(r'name="_csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)
