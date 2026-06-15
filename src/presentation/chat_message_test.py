"""チャットメッセージ表示routeのHTML契約を検証する。"""

import re
import sqlite3
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from src.presentation.test_support import (
    TestApplication,
    started_test_application,
)

from src.app import build_app
from src.config import AppConfig
from src.infrastructure import (
    AttachmentRepository,
    AuthRepository,
    BaseAssistantRepository,
    MessageRepository,
    ThreadRepository,
    utcnow,
)
from src.models import (
    AssistantGenerationConfig,
    Attachment,
    BaseAssistant,
    Message,
    MessageKind,
    MessageRole,
    MessageStatus,
    Thread,
)
from src.usecase.admin_user import AdminUserUsecaseContext, create_user


def test_chat_thread_renders_saved_reasoning_kind(tmp_path: Path) -> None:
    # 観点: 保存済みassistant messageのreasoning kindが初期HTMLへ出ること。
    # 目的: SSE完了後に再表示してもthinking領域をDBから復元できる契約を固定する。
    test_app = started_test_application(build_app(_config(tmp_path)))
    assistant_id = _ensure_default_assistant(test_app)
    client = test_app.client
    _login(client)
    with test_app.usecase_runtime.database.connect() as conn:
        user = AuthRepository(conn).get_by_login_name("admin")
        assert user is not None
        thread = save_thread(conn, user.id, "reasoning thread")
        assistant = save_assistant_placeholder(conn, thread.id, assistant_id)
        update_message(
            conn,
            assistant,
            content="visible answer",
            status=MessageStatus.COMPLETED,
            kinds=[MessageKind(kind="reasoning", content="thinking")],
        )
        conn.commit()

    response = client.get(f"/chat/{thread.id}")

    assert response.status_code == 200
    assert 'data-chat-raw-content="visible answer"' in response.text
    assert 'data-chat-raw-reasoning="thinking"' in response.text
    assert (
        '<details class="messageReasoning" data-chat-message-reasoning>'
        in response.text
    )
    assert response.text.index("data-chat-message-reasoning") < response.text.index(
        "data-chat-message-body"
    )


def test_chat_thread_opens_reasoning_for_processing_message(tmp_path: Path) -> None:
    # 観点: 生成中assistant messageのreasoningは初期HTMLで展開されること。
    # 目的: リロード時もstream中はreasoningを普通のメッセージのように見せる契約を固定する。
    test_app = started_test_application(build_app(_config(tmp_path)))
    assistant_id = _ensure_default_assistant(test_app)
    client = test_app.client
    _login(client)
    with test_app.usecase_runtime.database.connect() as conn:
        user = AuthRepository(conn).get_by_login_name("admin")
        assert user is not None
        thread = save_thread(conn, user.id, "processing reasoning")
        assistant = save_assistant_placeholder(conn, thread.id, assistant_id)
        update_message(
            conn,
            assistant,
            content="",
            status=MessageStatus.PROCESSING,
            kinds=[MessageKind(kind="reasoning", content="thinking")],
        )
        conn.commit()

    response = client.get(f"/chat/{thread.id}")

    assert response.status_code == 200
    assert (
        '<details class="messageReasoning" data-chat-message-reasoning open>'
        in response.text
    )


def test_chat_thread_hides_empty_user_bubble_for_attachment_only_message(
    tmp_path: Path,
) -> None:
    # 観点: 添付だけのユーザー発言では空本文バブルを描画しないこと。
    # 目的: 画像だけ投稿したときに不要な空メッセージ領域を見せない表示契約を固定する。
    test_app = started_test_application(build_app(_config(tmp_path)))
    client = test_app.client
    _login(client)
    with test_app.usecase_runtime.database.connect() as conn:
        user = AuthRepository(conn).get_by_login_name("admin")
        assert user is not None
        thread = save_thread(conn, user.id, "attachment only")
        attachment = save_attachment(
            conn,
            user_id=user.id,
            original_filename="photo.png",
            stored_path="1/photo.png",
            content_type="image/png",
            size_bytes=5,
            sha256="sha",
        )
        save_user_message(
            conn,
            thread.id,
            "",
            kinds=[MessageKind(kind="file", content=attachment.id)],
        )
        conn.commit()

    response = client.get(f"/chat/{thread.id}")

    assert response.status_code == 200
    assert "photo.png" in response.text
    assert 'data-chat-message-body data-chat-raw-content=""' not in response.text


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
    *,
    kinds: list[MessageKind] | None = None,
) -> Message:
    now = utcnow()
    return MessageRepository(conn).save(
        Message(
            id=0,
            thread_id=thread_id,
            role=MessageRole.USER,
            content=content,
            status=MessageStatus.COMPLETED,
            assistant_id=None,
            created_at=now,
            updated_at=now,
            kinds=kinds or [],
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


def update_message(
    conn: sqlite3.Connection,
    message: Message,
    *,
    content: str,
    status: MessageStatus,
    kinds: list[MessageKind] | None = None,
) -> Message:
    return MessageRepository(conn).update(
        replace(
            message,
            content=content,
            status=status,
            kinds=kinds or [],
            updated_at=utcnow(),
        )
    )


def save_attachment(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    original_filename: str,
    stored_path: str,
    content_type: str,
    size_bytes: int,
    sha256: str,
) -> Attachment:
    return AttachmentRepository(conn).save(
        Attachment(
            id=str(uuid4()),
            user_id=user_id,
            original_filename=original_filename,
            stored_path=stored_path,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
            created_at=utcnow(),
        )
    )


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
    response = client.post(
        "/login",
        data={
            "login_name": "admin",
            "password": "adminpass",
            "_csrf_token": _csrf_token(client.get("/login").text),
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


def _csrf_token(html: str) -> str:
    match = re.search(r'name="_csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _ensure_default_assistant(test_app: TestApplication) -> str:
    with test_app.usecase_runtime.database.connect() as conn:
        user = AuthRepository(conn).get_by_login_name("admin")
    if user is None:
        user = create_user(
            login_name="admin",
            password="adminpass",
            is_admin=True,
            context=AdminUserUsecaseContext(
                database=test_app.usecase_runtime.database,
                password_pepper="test-pepper",
                attachment_storage=test_app.usecase_runtime.attachment_storage,
            ),
        )
    with test_app.usecase_runtime.database.connect() as conn:
        assistants = BaseAssistantRepository(conn)
        existing = assistants.list_active()
        if existing:
            conn.commit()
            return existing[0].id
        created = save_base_assistant(
            conn,
            name="Default",
            description="",
            system_prompt="",
            user_prompts=[],
            connection_provider_id="openai",
            model="gpt-5-mini",
            generation_config={},
            max_history_messages=40,
            allow_file_upload=False,
        )
        conn.commit()
        return created.id
