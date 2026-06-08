import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app import build_app
from src.auth_password import hash_password
from src.config import AppConfig
from src.infrastructure import (
    AuthRepository,
    BaseAssistantRepository,
    Database,
    UserAssistantRepository,
)
from src.models import BaseAssistant, LlmMessage, User, UserAssistant
from src.service.response_service import StreamEvent


class FakeResponder:
    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent("delta", delta="ok")


def test_user_assistants_index_shows_user_specific_columns(tmp_path: Path) -> None:
    # 観点: 個人アシスタント一覧は元アシスタントと公開範囲を中心に表示すること。
    # 目的: 基本アシスタント向けの表示分岐を避け、個人一覧の専用責務を固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    base_id = _seed_base_assistant(app, tmp_path, "Default")
    user = _save_user(app.state.database, "user1", "pass123")
    _seed_user_assistant(app, base_id=base_id, owner_user_id=user.id, name="Personal")
    client = TestClient(app)
    _login(client, "user1", "pass123")

    response = client.get("/assistants")

    assert response.status_code == 200
    assert "Personal" in response.text
    assert "Base Assistant" in response.text
    assert "Visibility" in response.text
    assert "Provider" not in response.text
    assert "History" not in response.text
    assert "File upload" not in response.text
    assert "Owner" not in response.text


def test_user_assistant_form_exposes_base_selection_and_visibility(
    tmp_path: Path,
) -> None:
    # 観点: 個人アシスタント作成画面がBaseAssistant選択と公開範囲を表示すること。
    # 目的: 実行不能な個人アシスタントを作らないHTTPフォーム契約を固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    _seed_base_assistant(app, tmp_path, "Default")
    client = TestClient(app)
    _login(client)

    response = client.get("/assistants/new")

    assert response.status_code == 200
    assert 'id="base_assistant_id" name="base_assistant_id" required' in response.text
    assert ">&lt;not set&gt;</option>" in response.text
    assert 'name="visibility"' in response.text


def test_user_assistant_create_route_requires_base_assistant_id(
    tmp_path: Path,
) -> None:
    # 観点: My Assistant作成はBase Assistant未選択では保存できないこと。
    # 目的: ブラウザのrequiredを迂回したPOSTでもHTTP入口で400へ変換する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    _seed_base_assistant(app, tmp_path, "Default")
    client = TestClient(app)
    _login(client)
    new_page = client.get("/assistants/new")

    response = client.post(
        "/assistants/new",
        data={
            "base_assistant_id": "",
            "name": "No Base",
            "description": "",
            "user_prompts": "friendly",
            "visibility": "private",
            "_csrf_token": _csrf_token(new_page.text),
        },
        follow_redirects=False,
    )

    assert response.status_code == 400


def test_user_assistant_create_route_redirects_and_appears_in_chat(
    tmp_path: Path,
) -> None:
    # 観点: My Assistant作成POST後に自分のチャット選択肢へ表示されること。
    # 目的: ユーザー画面からチャット利用までのHTTP導線を固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    base_id = _seed_base_assistant(app, tmp_path, "Default")
    client = TestClient(app)
    _login(client)
    new_page = client.get("/assistants/new")

    response = client.post(
        "/assistants/new",
        data={
            "base_assistant_id": base_id,
            "name": "Personal",
            "description": "個人用",
            "user_prompts": "friendly",
            "visibility": "private",
            "_csrf_token": _csrf_token(new_page.text),
        },
        follow_redirects=False,
    )
    chat_page = client.get("/chat/new")

    assert response.status_code == 303
    assert "Personal" in chat_page.text


def test_user_assistant_update_route_redirects_and_lists_changes(
    tmp_path: Path,
) -> None:
    # 観点: My Assistant編集POSTが対象を更新して一覧へ戻ること。
    # 目的: update_user_assistant usecaseへのHTTPフォーム配線を固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    base_id = _seed_base_assistant(app, tmp_path, "Default")
    assistant_id = _seed_user_assistant(
        app,
        base_id=base_id,
        owner_user_id=1,
        name="Personal",
    )
    client = TestClient(app)
    _login(client)
    edit_page = client.get(f"/assistants/{assistant_id}/edit")

    response = client.post(
        f"/assistants/{assistant_id}/edit",
        data={
            "base_assistant_id": base_id,
            "name": "Personal Updated",
            "description": "更新済み",
            "user_prompts": "focused",
            "visibility": "public",
            "_csrf_token": _csrf_token(edit_page.text),
        },
        follow_redirects=False,
    )
    listed = client.get("/assistants")

    assert response.status_code == 303
    assert "Personal Updated" in listed.text


def test_user_assistant_delete_route_redirects_and_hides_assistant(
    tmp_path: Path,
) -> None:
    # 観点: My Assistant削除POSTが対象を一覧から隠すこと。
    # 目的: delete_user_assistant usecaseへのHTTPフォーム配線を固定する。
    app = build_app(_config(tmp_path), responder=FakeResponder())
    base_id = _seed_base_assistant(app, tmp_path, "Default")
    assistant_id = _seed_user_assistant(
        app,
        base_id=base_id,
        owner_user_id=1,
        name="Personal",
    )
    client = TestClient(app)
    _login(client)
    listed = client.get("/assistants")

    response = client.post(
        f"/assistants/{assistant_id}/delete",
        data={"_csrf_token": _csrf_token(listed.text)},
        follow_redirects=False,
    )
    after_delete = client.get("/assistants")

    assert response.status_code == 303
    assert "Personal" not in after_delete.text


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


def _seed_base_assistant(app: FastAPI, tmp_path: Path, name: str) -> str:
    _write_provider_config(tmp_path)
    with app.state.database.connect() as conn:
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
    with app.state.database.connect() as conn:
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


def _save_user(database: Database, login_name: str, password: str) -> User:
    with database.connect() as conn:
        user = AuthRepository(conn).save(
            User(id=0, login_name=login_name),
            password_hash=hash_password(password, "test-secret"),
        )
        conn.commit()
        return user


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
