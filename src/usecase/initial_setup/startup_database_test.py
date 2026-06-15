"""起動時DB整備 usecase の責務を検証する。"""

from pathlib import Path

from src.infrastructure import Database, MessageRepository, utcnow
from src.models import Message, MessageRole, MessageStatus
from src.usecase.initial_setup import (
    InitialSetupUsecaseContext,
    fail_processing_assistant_messages,
    initialize_database_schema,
)


def test_initialize_database_schema_creates_database_tables(tmp_path: Path) -> None:
    # 観点: 起動時DB schema初期化がDBファイルとactive_users表を用意すること。
    # 目的: app層から永続化初期化の詳細を切り離し、起動時usecaseの契約として固定する。
    database = Database(tmp_path / "chat.sqlite")

    initialize_database_schema(context=_context(database))

    with database.connect() as conn:
        count = conn.execute("select count(*) from active_users").fetchone()[0]

    assert count == 0


def test_fail_processing_assistant_messages_marks_unfinished_messages_failed(
    tmp_path: Path,
) -> None:
    # 観点: 起動時の未完了assistant message収束がprocessingをfailedへ更新すること。
    # 目的: 再起動で継続不能な応答をユーザー操作で回復できる状態へ明示的に落とす。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()
    message_id = _save_processing_assistant_message(database)

    fail_processing_assistant_messages(context=_context(database))

    with database.connect() as conn:
        stored = MessageRepository(conn).get(message_id)

    assert stored is not None
    assert stored.status is MessageStatus.FAILED


def _save_processing_assistant_message(database: Database) -> int:
    """テスト用にprocessing assistant messageを保存してIDを返す。"""
    now = utcnow().isoformat()
    with database.connect() as conn:
        conn.execute(
            """
            insert into active_users (
                id,
                login_name,
                password_hash,
                is_admin,
                created_at,
                updated_at
            )
            values (1, 'owner', 'hash', 1, :now, :now)
            """,
            {"now": now},
        )
        conn.execute(
            """
            insert into threads (id, user_id, title, created_at, updated_at)
            values ('thread-1', 1, 't', :now, :now)
            """,
            {"now": now},
        )
        message = MessageRepository(conn).save(
            Message(
                id=0,
                thread_id="thread-1",
                role=MessageRole.ASSISTANT,
                content="",
                status=MessageStatus.PROCESSING,
                assistant_id=None,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        conn.commit()
        return message.id


def _context(database: Database) -> InitialSetupUsecaseContext:
    """テスト用DBを持つ初回セットアップcontextを返す。"""
    return InitialSetupUsecaseContext(
        database=database,
        password_pepper="pepper",
    )
