import json
import re
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import NotRequired, TypedDict
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from src.presentation.test_support import (
    TestApplication,
    started_test_application,
    started_test_client,
)

from src.app import build_app
from src.config import AppConfig
from src.models import (
    AssistantGenerationConfig,
    BaseAssistant,
    LlmMessage,
    Message,
    MessageRole,
    MessageStatus,
    Thread,
)
from src.infrastructure import (
    AuthRepository,
    BaseAssistantRepository,
    MessageRepository,
    ThreadRepository,
    utcnow,
)
from src.service.response_service import StreamEvent
from src.usecase.initial_setup import create_initial_admin


class FakeResponder:
    async def stream(
        self, *, messages: list[LlmMessage], assistant: object
    ) -> AsyncIterator[StreamEvent]:
        yield StreamEvent("delta", delta="ok")


class AssistantSeed(TypedDict):
    name: str
    description: NotRequired[str]
    system_prompt: NotRequired[str]
    user_prompts: NotRequired[list[str]]
    model: NotRequired[str]
    max_history_messages: NotRequired[int]
    allow_file_upload: NotRequired[bool]


def save_thread(conn: sqlite3.Connection, user_id: int, title: str) -> Thread:
    now = utcnow()
    return ThreadRepository(conn).save(
        Thread(
            id=str(uuid4()),
            user_id=user_id,
            title=title.strip()[:80] or "New chat",
            created_at=now,
            updated_at=now,
        )
    )


def save_base_assistant(
    conn: sqlite3.Connection,
    *,
    name: str,
    description: str,
    system_prompt: str,
    user_prompts: list[str],
    connection_provider_id: str,
    model: str,
    generation_config: AssistantGenerationConfig,
    max_history_messages: int,
    allow_file_upload: bool,
) -> BaseAssistant:
    return BaseAssistantRepository(conn).save(
        BaseAssistant(
            id=str(uuid4()),
            name=name,
            description=description,
            system_prompt=system_prompt,
            user_prompts=user_prompts,
            connection_provider_id=connection_provider_id,
            model=model,
            generation_config=generation_config,
            max_history_messages=max_history_messages,
            allow_file_upload=allow_file_upload,
        )
    )


def save_user_message(
    conn: sqlite3.Connection,
    thread_id: str,
    content: str,
    assistant_id: str | None = None,
) -> Message:
    now = utcnow()
    return MessageRepository(conn).save(
        Message(
            id=0,
            thread_id=thread_id,
            role=MessageRole.USER,
            content=content,
            status=MessageStatus.COMPLETED,
            assistant_id=assistant_id,
            created_at=now,
            updated_at=now,
        )
    )


def save_assistant_placeholder(
    conn: sqlite3.Connection,
    thread_id: str,
    assistant_id: str | None = None,
) -> Message:
    now = utcnow()
    return MessageRepository(conn).save(
        Message(
            id=0,
            thread_id=thread_id,
            role=MessageRole.ASSISTANT,
            content="",
            status=MessageStatus.PROCESSING,
            assistant_id=assistant_id,
            created_at=now,
            updated_at=now,
        )
    )


def test_chat_route_requires_login_for_chat(tmp_path: Path) -> None:
    # 観点: チャット画面は未ログインでは表示されずログイン画面へ誘導されること。
    # 目的: 認証必須のHTTP境界をweb_routes側の責務として固定する。
    app = build_app(_config(tmp_path))

    response = started_test_client(app, follow_redirects=False).get("/chat")

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_chat_route_creates_chat_with_htmx(tmp_path: Path) -> None:
    # 観点: ログイン後にHTMXで新規チャットを作成し、URL push headerが返ること。
    # 目的: routeがservice群を配線してHTML fragmentを返す責務を固定する。
    test_app = started_test_application(build_app(_config(tmp_path)))
    created = _seed_standard_assistants(test_app, [{"name": "Default"}])
    client = test_app.client

    login_token = _csrf_token(client.get("/login").text)
    login = client.post(
        "/login",
        data={
            "login_name": "admin",
            "password": "adminpass",
            "_csrf_token": login_token,
        },
        follow_redirects=False,
    )
    page = client.get("/chat/new")
    response = client.post(
        "/chat/new",
        data={
            "content": "hello",
            "assistant_id": created["Default"],
            "_csrf_token": _csrf_token(page.text),
        },
        headers={"HX-Request": "true"},
    )

    assert login.status_code == 303
    assert response.status_code == 200
    assert response.headers["HX-Push-Url"].startswith("/chat/")
    assert "data-chat-stream-url" in response.text
    thread_id = response.headers["HX-Push-Url"].removeprefix("/chat/")
    assert 'hx-swap-oob="afterbegin:#thread-list"' in response.text
    assert f'id="thread-item-{thread_id}"' in response.text
    assert "hello" in response.text


def test_chat_route_does_not_log_message_preview_on_create(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 観点: 新規チャット作成時に本文previewがログへ残らないこと。
    # 目的: チャット本文を運用ログへ二次保管しない契約を固定する。
    test_app = started_test_application(
        build_app(_config(tmp_path), responder=FakeResponder())
    )
    created = _seed_standard_assistants(test_app, [{"name": "Default"}])
    client = test_app.client

    _login(client)
    capsys.readouterr()
    page = client.get("/chat/new")
    response = client.post(
        "/chat/new",
        data={
            "content": "secret-create-preview",
            "assistant_id": created["Default"],
            "_csrf_token": _csrf_token(page.text),
        },
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    captured = capsys.readouterr()
    assert "secret-create-preview" not in captured.err
    assert "preview=" not in captured.err
    assert "assistant_message_id=" in captured.err


def test_chat_route_does_not_log_message_preview_on_append(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 観点: 既存スレッドへの投稿時に本文previewがログへ残らないこと。
    # 目的: 追記投稿でも入力本文をログへ複製しない契約を固定する。
    test_app = started_test_application(
        build_app(_config(tmp_path), responder=FakeResponder())
    )
    created = _seed_standard_assistants(test_app, [{"name": "Default"}])
    client = test_app.client

    _login(client)
    capsys.readouterr()
    page = client.get("/chat/new")
    created_response = client.post(
        "/chat/new",
        data={
            "content": "seed",
            "assistant_id": created["Default"],
            "_csrf_token": _csrf_token(page.text),
        },
        headers={"HX-Request": "true"},
    )
    thread_id = created_response.headers["HX-Push-Url"].removeprefix("/chat/")
    thread_page = client.get(f"/chat/{thread_id}")
    capsys.readouterr()
    response = client.post(
        f"/chat/{thread_id}/messages",
        data={
            "content": "secret-append-preview",
            "assistant_id": created["Default"],
            "_csrf_token": _csrf_token(thread_page.text),
        },
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    captured = capsys.readouterr()
    assert "secret-append-preview" not in captured.err
    assert "preview=" not in captured.err
    assert "assistant_message_id=" in captured.err


def test_chat_route_uploads_attachment_when_assistant_allows_it(
    tmp_path: Path,
) -> None:
    # 観点: allow_file_upload=true のassistantではmultipart添付を保存し、表示と取得ができること。
    # 目的: UI/HTTP入口から認可付きファイル取得までの最小フローを固定する。
    test_app = started_test_application(
        build_app(_config(tmp_path), responder=FakeResponder())
    )
    created = _seed_standard_assistants(
        test_app,
        [{"name": "Default", "allow_file_upload": True}],
    )
    client = test_app.client
    _login(client)
    page = client.get("/chat/new")

    response = client.post(
        "/chat/new",
        data={
            "content": "",
            "assistant_id": created["Default"],
            "_csrf_token": _csrf_token(page.text),
        },
        files={"files": ("photo.png", b"image", "image/png")},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "photo.png" in response.text
    match = re.search(r'href="[^"]*/attachments/([^"]+)"', response.text)
    assert match is not None
    download = client.get(f"/attachments/{match.group(1)}")
    assert download.status_code == 200
    assert download.content == b"image"


def test_chat_route_rejects_attachment_when_assistant_disallows_it(
    tmp_path: Path,
) -> None:
    # 観点: allow_file_upload=false のassistantでは添付付きPOSTを拒否すること。
    # 目的: モデル非対応時にファイルが保存・LLM送信されない入口制御を固定する。
    test_app = started_test_application(
        build_app(_config(tmp_path), responder=FakeResponder())
    )
    created = _seed_standard_assistants(
        test_app,
        [{"name": "Default", "allow_file_upload": False}],
    )
    client = test_app.client
    _login(client)
    page = client.get("/chat/new")

    response = client.post(
        "/chat/new",
        data={
            "content": "hello",
            "assistant_id": created["Default"],
            "_csrf_token": _csrf_token(page.text),
        },
        files={"files": ("photo.png", b"image", "image/png")},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 400


def test_chat_route_rejects_post_with_invalid_csrf_token(tmp_path: Path) -> None:
    # 観点: 認証後の状態変更POSTは不正CSRFトークンで拒否されること。
    # 目的: protected routeがdependencyを明示していることを固定する。
    test_app = started_test_application(build_app(_config(tmp_path)))
    created = _seed_standard_assistants(test_app, [{"name": "Default"}])
    client = test_app.client

    login_token = _csrf_token(client.get("/login").text)
    client.post(
        "/login",
        data={
            "login_name": "admin",
            "password": "adminpass",
            "_csrf_token": login_token,
        },
        follow_redirects=False,
    )

    response = client.post(
        "/chat/new",
        data={
            "content": "hello",
            "assistant_id": created["Default"],
            "_csrf_token": "invalid",
        },
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 403


def test_chat_route_delete_thread_from_sidebar_logically_hides_it(
    tmp_path: Path,
) -> None:
    # 観点: サイドバーの削除POSTで対象threadが画面と詳細URLから見えなくなること。
    # 目的: 確認付き削除UIがHTTP境界では論理削除routeへ到達する契約を固定する。
    test_app = started_test_application(
        build_app(_config(tmp_path), responder=FakeResponder())
    )
    created = _seed_standard_assistants(test_app, [{"name": "Default"}])
    client = test_app.client
    _login(client)
    page = client.get("/chat/new")
    created = client.post(
        "/chat/new",
        data={
            "content": "remove me",
            "assistant_id": created["Default"],
            "_csrf_token": _csrf_token(page.text),
        },
        headers={"HX-Request": "true"},
    )
    thread_id = created.headers["HX-Push-Url"].removeprefix("/chat/")

    thread_page = client.get(f"/chat/{thread_id}")
    response = client.post(
        f"/chat/{thread_id}/delete",
        data={"_csrf_token": _csrf_token(thread_page.text)},
        follow_redirects=False,
    )
    deleted_page = client.get(f"/chat/{thread_id}")
    home = client.get("/chat", follow_redirects=False)

    assert "threadDeleteButton" in thread_page.text
    assert 'onsubmit="return confirm(' in thread_page.text
    assert response.status_code == 303
    assert deleted_page.status_code == 404
    assert home.status_code == 200
    assert "remove me" not in home.text


def test_chat_route_edit_thread_title_with_htmx_updates_sidebar(
    tmp_path: Path,
) -> None:
    # 観点: HTMXで中央寄せタイトルをアイコン編集し、blurで元表示へ戻せること。
    # 目的: タイトル編集のHTTP断片契約を固定し、軽いインライン編集UXを崩さないようにする。
    test_app = started_test_application(
        build_app(_config(tmp_path), responder=FakeResponder())
    )
    created = _seed_standard_assistants(test_app, [{"name": "Default"}])
    client = test_app.client
    _login(client)
    page = client.get("/chat/new")
    created_chat = client.post(
        "/chat/new",
        data={
            "content": "before title",
            "assistant_id": created["Default"],
            "_csrf_token": _csrf_token(page.text),
        },
        headers={"HX-Request": "true"},
    )
    thread_id = created_chat.headers["HX-Push-Url"].removeprefix("/chat/")

    thread_page = client.get(f"/chat/{thread_id}")
    edit = client.get(
        f"/chat/{thread_id}/title/edit",
        headers={"HX-Request": "true"},
    )
    updated = client.post(
        f"/chat/{thread_id}/title",
        data={
            "title": "renamed chat",
            "_csrf_token": _csrf_token(thread_page.text),
        },
        headers={"HX-Request": "true"},
    )
    refreshed = client.get(f"/chat/{thread_id}")

    assert edit.status_code == 200
    assert 'data-select-on-focus="true"' in edit.text
    assert "data-thread-title-edit" in edit.text
    assert f'hx-post="/chat/{thread_id}/title"' in edit.text
    assert ">Save</button>" not in edit.text
    assert ">Cancel</button>" not in edit.text
    assert "fa-check" in edit.text
    assert "data-thread-title-edit-input" in edit.text
    assert updated.status_code == 200
    assert 'id="thread-title"' in updated.text
    assert "renamed chat" in updated.text
    assert 'hx-swap-oob="true"' in updated.text
    assert f'id="thread-item-{thread_id}"' in updated.text
    assert "threadTitleCenter" in updated.text
    assert "fa-pen" in updated.text
    assert "renamed chat" in refreshed.text


def test_message_meta_shows_assistant_name_only_for_assistant_messages(
    tmp_path: Path,
) -> None:
    # 観点: アシスタント名はassistant発言にだけ表示し、ユーザー発言には出さないこと。
    # 目的: ユーザーが選択して送信したassistant_idを人間の発言者名として誤表示しない。
    test_app = started_test_application(
        build_app(_config(tmp_path), responder=FakeResponder())
    )
    created = _seed_standard_assistants(test_app, [{"name": "Default"}])
    with test_app.usecase_runtime.database.connect() as conn:
        admin = AuthRepository(conn).get_by_login_name("admin")
        assert admin is not None
        thread = save_thread(conn, admin.id, "hello")
        save_user_message(
            conn,
            thread.id,
            "hello",
            created["Default"],
        )
        save_assistant_placeholder(
            conn,
            thread.id,
            created["Default"],
        )
        conn.commit()
    client = test_app.client
    _login(client)

    response = client.get(f"/chat/{thread.id}")

    assert response.text.count('<span class="messageAssistantName">Default</span>') == 1


def test_chat_new_page_renders_idle_composer(tmp_path: Path) -> None:
    # 観点: 新規チャット画面は未処理状態の入力フォームを表示すること。
    # 目的: 応答生成中ではない通常画面のHTTP表示契約を固定する。
    test_app = started_test_application(
        build_app(_config(tmp_path), responder=FakeResponder())
    )
    _seed_standard_assistants(test_app, [{"name": "Default"}])
    client = test_app.client
    _login(client)

    response = client.get("/chat/new")

    assert response.status_code == 200
    assert "data-chat-composer" in response.text
    assert "data-chat-status" not in response.text


def test_processing_message_shows_cancel_button_and_locks_form(
    tmp_path: Path,
) -> None:
    # 観点: 応答生成中のassistant messageがある画面では送信欄が処理中として扱われること。
    # 目的: 追加送信を止めつつ、ユーザーが途中中断できるHTML契約を固定する。
    test_app = started_test_application(
        build_app(_config(tmp_path), responder=FakeResponder())
    )
    created = _seed_standard_assistants(test_app, [{"name": "Default"}])
    client = test_app.client
    _login(client)
    with test_app.usecase_runtime.database.connect() as conn:
        user = AuthRepository(conn).get_by_login_name("admin")
        assert user is not None
        thread = save_thread(conn, user.id, "slow answer")
        save_user_message(conn, thread.id, "slow answer", created["Default"])
        save_assistant_placeholder(conn, thread.id, created["Default"])
        conn.commit()

    response = client.get(f"/chat/{thread.id}")

    assert response.status_code == 200
    assert 'data-chat-processing="true"' in response.text
    assert "data-chat-cancel-button" in response.text
    assert f'hx-post="/chat/{thread.id}/messages/' in response.text
    assert "/cancel" in response.text
    assert 'aria-label="Stop response"' in response.text


def test_cancel_response_route_accepts_owned_processing_message_cancel(
    tmp_path: Path,
) -> None:
    # 観点: 所有スレッドの生成中assistant messageをHTTP POSTで中断できること。
    # 目的: 生成状態の永続化ではなく、キャンセル操作のHTTP入口契約を固定する。
    test_app = started_test_application(
        build_app(_config(tmp_path), responder=FakeResponder())
    )
    created = _seed_standard_assistants(test_app, [{"name": "Default"}])
    client = test_app.client
    _login(client)
    with test_app.usecase_runtime.database.connect() as conn:
        user = AuthRepository(conn).get_by_login_name("admin")
        assert user is not None
        thread = save_thread(conn, user.id, "cancel me")
        save_user_message(conn, thread.id, "cancel me", created["Default"])
        assistant = save_assistant_placeholder(conn, thread.id, created["Default"])
        conn.commit()
    thread_page = client.get(f"/chat/{thread.id}")

    response = client.post(
        f"/chat/{thread.id}/messages/{assistant.id}/cancel",
        data={"_csrf_token": _csrf_token(thread_page.text)},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 204


def test_sidebar_shows_logged_in_user_and_icon_only_logout(
    tmp_path: Path,
) -> None:
    # 観点: サイドバーにログイン済みユーザー名が表示されること。
    # 目的: HTTP表示でセッション中のアカウント状態を確認できる契約を固定する。
    test_app = started_test_application(
        build_app(_config(tmp_path), responder=FakeResponder())
    )
    client = test_app.client
    _login(client)

    response = client.get("/chat/new")

    assert response.status_code == 200
    assert "admin" in response.text
    assert "sidebarAccountPanel" in response.text


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


def _seed_standard_assistants(
    test_app: TestApplication,
    assistants: list[AssistantSeed],
) -> dict[str, str]:
    config = test_app.usecase_runtime.config
    (config.data_dir / "connection_providers.json").write_text(
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
    with test_app.usecase_runtime.database.connect() as conn:
        auth = AuthRepository(conn)
        admin = auth.get_by_login_name("admin")
    if admin is None:
        admin = create_initial_admin(
            login_name="admin",
            password="adminpass",
        )
    with test_app.usecase_runtime.database.connect() as conn:
        created_by_name: dict[str, str] = {}
        for item in assistants:
            max_history = item.get("max_history_messages", 40)
            created = save_base_assistant(
                conn,
                name=str(item["name"]),
                description=str(item.get("description", "")),
                system_prompt=str(item.get("system_prompt", "")),
                user_prompts=[
                    str(prompt)
                    for prompt in item.get("user_prompts", [])
                    if prompt.strip()
                ],
                connection_provider_id="openai",
                model=str(item.get("model", "gpt-5-mini")),
                generation_config={},
                max_history_messages=max_history,
                allow_file_upload=bool(item.get("allow_file_upload", False)),
            )
            created_by_name[created.name] = created.id
        conn.commit()
    return created_by_name


def _csrf_token(html: str) -> str:
    match = re.search(r'name="_csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)
