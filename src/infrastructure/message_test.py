"""MessageRepositoryの保存・状態収束責務を検証する。"""

import sqlite3
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from src.service.password import hash_password
from src.models import Message, MessageKind, MessageRole, MessageStatus, Thread, User
from src.infrastructure import (
    AuthRepository,
    Database,
    MessageRepository,
    ThreadRepository,
    utcnow,
)


def test_message_repository_saves_and_updates_message_kinds(tmp_path: Path) -> None:
    # 観点: Messageモデル保存時に本文と追加kindをmessage_kindsへ保存・復元できること。
    # 目的: content列を持たないDB構造でもMessage契約を保つ。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        user = save_user(conn, "pepper", "admin", "adminpass")
        thread = save_thread(conn, user.id, "title")
        repo = MessageRepository(conn)
        assistant = save_assistant_placeholder(conn, thread.id, "default")
        updated = update_message(
            conn,
            assistant,
            content="answer",
            status=MessageStatus.COMPLETED,
            kinds=[
                MessageKind(kind="reasoning", content="thought"),
                MessageKind(kind="file", content="data/report.txt"),
            ],
        )
        loaded = repo.get(assistant.id)
        conn.commit()

    assert updated.content == "answer"
    assert loaded.content == "answer"
    assert [kind.kind for kind in loaded.kinds] == ["text", "reasoning", "file"]


def test_message_repository_lists_thread_messages_in_insert_order(
    tmp_path: Path,
) -> None:
    # 観点: 同一threadのuser/assistant messageを保存順で取得できること。
    # 目的: チャット画面が会話順序をRepositoryのlist_by_threadから復元できる契約を固定する。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        user = save_user(conn, "pepper", "admin", "adminpass")
        thread = save_thread(conn, user.id, "first title")
        user_message = save_user_message(conn, thread.id, "hello")
        assistant_message = save_assistant_placeholder(conn, thread.id)
        loaded = MessageRepository(conn).list_by_thread(thread.id)
        conn.commit()

    assert isinstance(user_message.id, int)
    assert isinstance(assistant_message.id, int)
    assert [message.role for message in loaded] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert [message.id for message in loaded] == [
        user_message.id,
        assistant_message.id,
    ]


def test_message_repository_marks_processing_assistant_messages_failed(
    tmp_path: Path,
) -> None:
    # 観点: 再起動時にprocessing assistant messageをfailedへ収束できること。
    # 目的: 未完了ジョブを自動再実行しない永続化ポリシーを固定する。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        user = save_user(conn, "pepper", "admin", "adminpass")
        thread = save_thread(conn, user.id, "title")
        repo = MessageRepository(conn)
        processing = save_assistant_placeholder(conn, thread.id, "default")
        completed = update_message(
            conn,
            save_assistant_placeholder(conn, thread.id, "default"),
            content="done",
            status=MessageStatus.COMPLETED,
        )
        changed = repo.fail_processing_assistant_messages()
        loaded = {message.id: message for message in repo.list_by_thread(thread.id)}
        conn.commit()

    assert changed == 1
    assert loaded[processing.id].status is MessageStatus.FAILED
    assert loaded[completed.id].status is MessageStatus.COMPLETED


def test_message_repository_updates_processing_message_to_terminal_once(
    tmp_path: Path,
) -> None:
    # 観点: processing messageだけをterminalへ条件付き更新できること。
    # 目的: 応答完了とcancelが競合しても後着の結果でDBを上書きしない。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        user = save_user(conn, "pepper", "admin", "adminpass")
        thread = save_thread(conn, user.id, "title")
        repo = MessageRepository(conn)
        processing = save_assistant_placeholder(conn, thread.id, "default")
        first = replace(
            processing,
            content="partial",
            status=MessageStatus.FAILED,
            kinds=[MessageKind(kind="reasoning", content="thinking")],
            updated_at=utcnow(),
        )
        second = replace(
            processing,
            content="complete",
            status=MessageStatus.COMPLETED,
            updated_at=utcnow(),
        )

        changed = repo.update_processing_to_terminal(first)
        existing = repo.update_processing_to_terminal(second)
        loaded = repo.get(processing.id)
        conn.commit()

    assert changed is not None
    assert existing is not None
    assert existing.status is MessageStatus.FAILED
    assert existing.content == "partial"
    assert loaded.status is MessageStatus.FAILED
    assert loaded.content == "partial"
    assert [kind.kind for kind in loaded.kinds] == ["text", "reasoning"]


def test_message_repository_terminal_update_returns_none_for_missing_message(
    tmp_path: Path,
) -> None:
    # 観点: 対象messageが消えた場合に条件付き更新が冪等なNoneになること。
    # 目的: 応答Taskの失敗処理が元例外を上書きせず対象なしへ収束する。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        missing = Message(
            id=999,
            thread_id="missing",
            role=MessageRole.ASSISTANT,
            content="answer",
            status=MessageStatus.COMPLETED,
            assistant_id="default",
            created_at=utcnow(),
            updated_at=utcnow(),
        )

        changed = MessageRepository(conn).update_processing_to_terminal(missing)

    assert changed is None


@pytest.mark.parametrize("status", [MessageStatus.PROCESSING])
def test_message_repository_rejects_non_terminal_status_for_conditional_update(
    tmp_path: Path,
    status: MessageStatus,
) -> None:
    # 観点: 条件付き終端更新へprocessingを渡せないこと。
    # 目的: Repository境界で状態遷移の向きを固定し、呼出し側の実装ミスを検知する。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        message = Message(
            id=999,
            thread_id="missing",
            role=MessageRole.ASSISTANT,
            content="answer",
            status=status,
            assistant_id="default",
            created_at=utcnow(),
            updated_at=utcnow(),
        )

        with pytest.raises(ValueError, match="terminal"):
            MessageRepository(conn).update_processing_to_terminal(message)


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
