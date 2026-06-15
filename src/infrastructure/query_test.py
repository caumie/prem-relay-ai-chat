"""repositoriesパッケージのQuery系読み取り境界を検証する。"""

import sqlite3
from pathlib import Path
from uuid import uuid4

from src.service.password import hash_password
from src.models import (
    AssistantGenerationConfig,
    AssistantVisibility,
    BaseAssistant,
    Message,
    MessageRole,
    MessageStatus,
    Thread,
    User,
    UserAssistant,
)
from src.infrastructure import (
    AssistantSelectionQuery,
    AuthRepository,
    BaseAssistantRepository,
    ChatThreadQuery,
    Database,
    MessageRepository,
    ThreadRepository,
    UserAssistantRepository,
    utcnow,
)


def test_chat_thread_query_reads_visible_thread_detail_for_owner(
    tmp_path: Path,
) -> None:
    # 観点: チャット詳細表示が所有者付きthreadとmessage一覧をまとめて読めること。
    # 目的: CRUD保存操作と、画面要求に応じた読み取りQueryの責務を分けて固定する。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        user = save_user(conn, "pepper", "user", "pass")
        other = save_user(conn, "pepper", "other", "pass")
        thread = save_thread(conn, user.id, "visible")
        save_user_message(conn, thread.id, "hello")
        save_assistant_placeholder(conn, thread.id, "assistant")
        query = ChatThreadQuery(conn)
        owned = query.get_detail_for_user(thread_id=thread.id, user_id=user.id)
        rejected = query.get_detail_for_user(thread_id=thread.id, user_id=other.id)
        sidebar = query.list_sidebar_threads(user.id)
        conn.commit()

    assert owned is not None
    assert owned.thread == thread
    assert [message.content for message in owned.messages] == ["hello", ""]
    assert rejected is None
    assert sidebar == [thread]


def test_assistant_selection_query_reads_chat_options_by_domain_order(
    tmp_path: Path,
) -> None:
    # 観点: チャット選択肢が所有UserAssistant、BaseAssistant、他者publicの順で読めること。
    # 目的: アシスタント選択画面の読み取り規則をCRUD一覧操作から独立させる。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        user = save_user(conn, "pepper", "user", "pass")
        other = save_user(conn, "pepper", "other", "pass")
        base = save_base_assistant(
            conn,
            name="Base",
            description="base",
            system_prompt="system",
            user_prompts=[],
            connection_provider_id="openai",
            model="gpt-5",
            generation_config={},
            max_history_messages=20,
            allow_file_upload=True,
            allowed_file_extensions=["jpg", "png"],
        )
        owned = save_user_assistant(
            conn,
            base_assistant_id=base.id,
            owner_user_id=user.id,
            name="Owned",
            description="owned",
            user_prompts=[],
            visibility="private",
        )
        public = save_user_assistant(
            conn,
            base_assistant_id=base.id,
            owner_user_id=other.id,
            name="Public",
            description="public",
            user_prompts=[],
            visibility="public",
        )
        options = AssistantSelectionQuery(conn).list_chat_options(user.id)
        conn.commit()

    assert [option.id for option in options] == [owned.id, base.id, public.id]
    assert [option.category for option in options] == [
        "owned",
        "system_public",
        "other_public",
    ]
    assert all(option.allow_file_upload for option in options)
    assert all(option.allowed_file_extensions == ["jpg", "png"] for option in options)


def save_user(
    conn: sqlite3.Connection,
    password_pepper: str,
    login_name: str,
    password: str,
) -> User:
    return AuthRepository(conn).create(
        login_name=login_name,
        is_admin=False,
        password_hash=hash_password(password, password_pepper),
    )


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
    allowed_file_extensions: list[str] | None = None,
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
            allowed_file_extensions=allowed_file_extensions or ["jpg", "jpeg", "png"],
        )
    )


def save_user_assistant(
    conn: sqlite3.Connection,
    *,
    base_assistant_id: str | None,
    owner_user_id: int,
    name: str,
    description: str,
    user_prompts: list[str],
    visibility: AssistantVisibility,
) -> UserAssistant:
    return UserAssistantRepository(conn).save(
        UserAssistant(
            id=str(uuid4()),
            base_assistant_id=base_assistant_id,
            owner_user_id=owner_user_id,
            name=name,
            description=description,
            user_prompts=user_prompts,
            visibility=visibility,
        )
    )


def save_user_message(
    conn: sqlite3.Connection,
    thread_id: str,
    content: str,
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
