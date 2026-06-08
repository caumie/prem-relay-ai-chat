"""admin user ユースケースの責務を検証する。"""

from pathlib import Path

from src.auth_password import verify_password
from src.infrastructure import (
    AttachmentRepository,
    AttachmentStorage,
    AuthRepository,
    Database,
    UserAssistantRepository,
    utcnow,
)
from src.models import Attachment, UserAssistant
from src.usecase.context import UsecaseContext
from src.usecase.test_support import FakeResponseStarter

from .create_user import create_user
from .delete_user import delete_user
from .suspend_user import suspend_user
from .update_user import update_user


def test_create_user_persists_trimmed_login_name_and_password_hash(
    tmp_path: Path,
) -> None:
    # 観点: user作成ユースケースがlogin_name整形とパスワード保存形式を担うこと。
    # 目的: routeが整形やハッシュ詳細を持たずにuser作成を委譲できるようにする。
    context = _context(tmp_path)
    database = context.database

    created = create_user(
        context, login_name="  user1  ", password="pass123", is_admin=True
    )

    with database.connect() as conn:
        stored = AuthRepository(conn).get_user(created.id)
        password_hash = AuthRepository(conn).get_password_hash_by_login_name("user1")

    assert stored is not None
    assert stored.login_name == "user1"
    assert stored.is_admin is True
    assert password_hash is not None
    assert verify_password("pass123", password_hash, "pepper")


def test_update_user_rewrites_login_name_admin_flag_and_password(
    tmp_path: Path,
) -> None:
    # 観点: user更新ユースケースが属性変更と任意パスワード変更を一括で扱うこと。
    # 目的: 編集画面が更新条件分岐を持たずに更新処理を委譲できるようにする。
    context = _context(tmp_path)
    database = context.database
    created = create_user(
        context, login_name="user1", password="pass123", is_admin=False
    )

    updated = update_user(
        context,
        user_id=created.id,
        login_name="  user1-updated  ",
        password="pass456",
        is_admin=True,
    )

    with database.connect() as conn:
        password_hash = AuthRepository(conn).get_password_hash_by_login_name(
            "user1-updated"
        )

    assert updated.login_name == "user1-updated"
    assert updated.is_admin is True
    assert password_hash is not None
    assert verify_password("pass456", password_hash, "pepper")


def test_suspend_user_marks_user_as_suspended(tmp_path: Path) -> None:
    # 観点: user休止ユースケースが対象ユーザーを休止状態へ遷移させること。
    # 目的: 管理画面の休止操作が認証可否に効く状態変更だけをusecaseへ委譲できるようにする。
    context = _context(tmp_path)
    database = context.database
    created = create_user(
        context, login_name="user1", password="pass123", is_admin=False
    )

    suspended = suspend_user(context, user_id=created.id)

    with database.connect() as conn:
        stored = AuthRepository(conn).get_user(created.id)

    assert suspended is True
    assert stored is not None
    assert stored.suspended_at is not None


def test_delete_user_removes_related_records_and_attachment_file(
    tmp_path: Path,
) -> None:
    # 観点: user削除ユースケースが関連レコードと添付ファイルをまとめて削除すること。
    # 目的: 管理画面が削除順序や保存ファイル整合を知らずに削除処理を委譲できるようにする。
    context = _context(tmp_path)
    database = context.database
    uploads_dir = context.uploads_dir
    created = create_user(
        context, login_name="user1", password="pass123", is_admin=False
    )
    stored_file = uploads_dir / str(created.id) / "photo.png"
    stored_file.parent.mkdir(parents=True, exist_ok=True)
    stored_file.write_bytes(b"abc")

    with database.connect() as conn:
        conn.execute(
            """
            insert into threads(id, user_id, title, deleted_at, created_at, updated_at)
            values('thread-1', :user_id, 'delete target', null, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            {"user_id": created.id},
        )
        UserAssistantRepository(conn).save(
            UserAssistant(
                id="ua-1",
                base_assistant_id=None,
                owner_user_id=created.id,
                name="personal",
                description="",
                user_prompts=[],
                visibility="private",
            )
        )
        AttachmentRepository(conn).save(
            Attachment(
                id="att-1",
                user_id=created.id,
                original_filename="photo.png",
                stored_path=f"{created.id}/photo.png",
                content_type="image/png",
                size_bytes=3,
                sha256="abc123",
                created_at=utcnow(),
            )
        )
        conn.commit()

    deleted = delete_user(context, user_id=created.id)

    with database.connect() as conn:
        active_user = AuthRepository(conn).get_user(created.id)
        deleted_name = conn.execute(
            "select login_name from deleted_users where login_name = ?",
            ("user1",),
        ).fetchone()
        attachment_count = conn.execute(
            "select count(*) from attachments where user_id = ?",
            (created.id,),
        ).fetchone()[0]
        thread_count = conn.execute(
            "select count(*) from threads where user_id = ?",
            (created.id,),
        ).fetchone()[0]
        user_assistant_count = conn.execute(
            "select count(*) from user_assistants where owner_user_id = ?",
            (created.id,),
        ).fetchone()[0]

    assert deleted is True
    assert active_user is None
    assert deleted_name is not None
    assert attachment_count == 0
    assert thread_count == 0
    assert user_assistant_count == 0
    assert not stored_file.exists()


def _context(tmp_path: Path) -> UsecaseContext:
    """admin user ユースケース用のcontextを初期化して返す。"""
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()
    uploads_dir = tmp_path / "uploads"
    return UsecaseContext(
        database=database,
        password_pepper="pepper",
        response_service=FakeResponseStarter(),
        uploads_dir=uploads_dir,
        attachment_storage=AttachmentStorage(uploads_dir),
        load_connection_providers=lambda: [],
    )
