import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.presentation.test_support import (
    usecase_runtime_for,
    started_test_client,
)

from src.app import build_app
from src.config import AppConfig
from src.infrastructure import (
    BaseAssistantRepository,
    UserAssistantRepository,
)
from src.models import BaseAssistant, LlmMessage, User, UserAssistant
from src.service.response_service import StreamEvent
from src.usecase.admin_user import AdminUserUsecaseContext, create_user


class FakeResponder:
    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent("delta", delta="ok")


def test_admin_user_assistants_index_shows_creator_and_missing_base(
    tmp_path: Path,
) -> None:
    # 観点: 管理者のUserAssistant一覧では作成者名と元BaseAssistant状態を出すこと。
    # 目的: BaseAssistant削除後も割り当てなしとして編集可能な状態を固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    base_id = _seed_base_assistant(app, tmp_path, "Default")
    creator = _create_user(app, "creator1", "pass123")
    _seed_user_assistant(
        app,
        base_id=base_id,
        owner_user_id=creator.id,
        name="Creator Assistant",
    )
    with usecase_runtime_for(app).database.connect() as conn:
        BaseAssistantRepository(conn).logical_delete(base_assistant_id=base_id)
        conn.commit()
    client = started_test_client(app)
    _login(client)

    response = client.get("/admin/user-assistants")

    assert response.status_code == 200
    assert "Creator Assistant" in response.text
    assert "creator1" in response.text
    assert "Not set" in response.text


def test_admin_user_assistant_create_route_redirects_and_lists_assistant(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 観点: 管理者のUserAssistant作成POSTがフォーム入力を受け取り一覧へ戻ること。
    # 目的: admin user assistant作成のHTTP入口配線を固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    base_id = _seed_base_assistant(app, tmp_path, "Default")
    client = started_test_client(app)
    _login(client)
    new_page = client.get("/admin/user-assistants/new")

    response = client.post(
        "/admin/user-assistants/new",
        data={
            "base_assistant_id": base_id,
            "name": "Managed",
            "description": "管理者作成",
            "user_prompts": "admin prompt",
            "visibility": "private",
            "_csrf_token": _csrf_token(new_page.text),
        },
        follow_redirects=False,
    )
    listed = client.get("/admin/user-assistants")

    assert response.status_code == 303
    assert "Managed" in listed.text
    captured = capsys.readouterr()
    assert "audit.admin_user_assistant.created" in captured.err


def test_admin_user_assistant_update_route_redirects_and_lists_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 観点: 管理者のUserAssistant編集POSTが対象を更新して一覧へ戻ること。
    # 目的: admin user assistant更新のHTTP入口配線を固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    base_id = _seed_base_assistant(app, tmp_path, "Default")
    assistant_id = _seed_user_assistant(
        app,
        base_id=base_id,
        owner_user_id=1,
        name="Managed",
    )
    client = started_test_client(app)
    _login(client)
    edit_page = client.get(f"/admin/user-assistants/{assistant_id}/edit")

    response = client.post(
        f"/admin/user-assistants/{assistant_id}/edit",
        data={
            "base_assistant_id": base_id,
            "name": "Managed Updated",
            "description": "更新済み",
            "user_prompts": "focused",
            "visibility": "public",
            "_csrf_token": _csrf_token(edit_page.text),
        },
        follow_redirects=False,
    )
    listed = client.get("/admin/user-assistants")

    assert response.status_code == 303
    assert "Managed Updated" in listed.text
    captured = capsys.readouterr()
    assert "audit.admin_user_assistant.updated" in captured.err


def test_admin_user_assistant_delete_route_redirects_and_hides_assistant(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 観点: 管理者のUserAssistant削除POSTが対象を一覧から隠すこと。
    # 目的: admin user assistant削除のHTTP入口配線を固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    base_id = _seed_base_assistant(app, tmp_path, "Default")
    assistant_id = _seed_user_assistant(
        app,
        base_id=base_id,
        owner_user_id=1,
        name="Managed",
    )
    client = started_test_client(app)
    _login(client)
    listed = client.get("/admin/user-assistants")

    response = client.post(
        f"/admin/user-assistants/{assistant_id}/delete",
        data={"_csrf_token": _csrf_token(listed.text)},
        follow_redirects=False,
    )
    after_delete = client.get("/admin/user-assistants")

    assert response.status_code == 303
    assert "Managed" not in after_delete.text
    captured = capsys.readouterr()
    assert "audit.admin_user_assistant.deleted" in captured.err


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        db_path=tmp_path / "chat.sqlite",
        data_dir=tmp_path,
        uploads_dir=tmp_path / "uploads",
        session_secret="test-secret",
        password_pepper="test-pepper",
    )


def _login(client: TestClient) -> None:
    _ensure_initial_admin(client)
    login_token = _csrf_token(client.get("/login").text)
    response = client.post(
        "/login",
        data={
            "login_name": "admin",
            "password": "adminpass",
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


def _seed_base_assistant(app: FastAPI, tmp_path: Path, name: str) -> str:
    _write_provider_config(tmp_path)
    with usecase_runtime_for(app).database.connect() as conn:
        created = BaseAssistantRepository(conn).save(
            BaseAssistant(
                id=str(uuid4()),
                name=name,
                description="",
                system_prompt="system",
                user_prompts=[],
                connection_provider_id="openai",
                model="gpt-5-mini",
                generation_config={},
                max_history_messages=40,
                allow_file_upload=False,
            )
        )
        conn.commit()
        return created.id


def _seed_user_assistant(
    app: FastAPI,
    *,
    base_id: str,
    owner_user_id: int,
    name: str,
) -> str:
    _ensure_user_exists(app, user_id=owner_user_id)
    with usecase_runtime_for(app).database.connect() as conn:
        created = UserAssistantRepository(conn).save(
            UserAssistant(
                id=str(uuid4()),
                base_assistant_id=base_id,
                owner_user_id=owner_user_id,
                name=name,
                description="個人用",
                user_prompts=["friendly"],
                visibility="private",
            )
        )
        conn.commit()
        return created.id


def _ensure_user_exists(app: FastAPI, *, user_id: int) -> None:
    """直接seedで参照するユーザーを不足時だけ作成する。"""
    with usecase_runtime_for(app).database.connect() as conn:
        if conn.execute(
            "select 1 from active_users where id = :id",
            {"id": user_id},
        ).fetchone():
            return
    create_user(
        login_name="admin" if user_id == 1 else f"user{user_id}",
        password="adminpass" if user_id == 1 else "pass123",
        is_admin=user_id == 1,
        context=AdminUserUsecaseContext(
            database=usecase_runtime_for(app).database,
            password_pepper="test-pepper",
            attachment_storage=usecase_runtime_for(app).attachment_storage,
        ),
    )


def _create_user(app: FastAPI, login_name: str, password: str) -> User:
    """admin user作成ユースケースでテストユーザーを作る。

    Args:
        app: build_appで生成したFastAPIアプリ。
        login_name: 作成するログイン名。
        password: 作成するユーザーの平文パスワード。

    Returns:
        作成済みユーザー。

    routeテストがユーザー保存形式を直接持たずに所有者前提を作れるようにする。
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


def _write_provider_config(tmp_path: Path) -> None:
    (tmp_path / "connection_providers.json").write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "openai",
                        "name": "OpenAI",
                        "api_mode": "responses",
                        "api_key": "test",
                        "base_url": "https://api.openai.com/v1",
                        "allowed_models": ["gpt-5", "gpt-5-mini"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _csrf_token(html: str) -> str:
    match = re.search(r'name="_csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)
