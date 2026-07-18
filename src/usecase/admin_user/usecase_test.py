"""admin user ユースケースの責務を検証する。"""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.service.password import verify_password
from src.infrastructure import (
    AttachmentRepository,
    AttachmentStorage,
    AuthRepository,
    Database,
    UserAssistantRepository,
    utcnow,
)
from src.config import AppConfig
from src.models import Attachment, User, UserAssistant
from src.usecase.admin_user import (
    AdminUserUsecaseContext,
    admin_user_usecase_context,
    create_user,
    delete_user,
    suspend_user,
    update_user,
)
from src.usecase.admin_user.errors import (
    CannotModifyCurrentAdminError,
    LastActiveAdminError,
)
from src.usecase.runtime import init_usecase_runtime


class TestAdminUserUsecaseContext:
    """admin_user_usecase_context の依存抽出を検証する。"""

    def test_contains_only_admin_user_dependencies(self, tmp_path: Path) -> None:
        """共有runtimeからadmin userに必要な依存だけを取り出す。"""
        # 観点: admin user usecase context がconfigを業務用依存へ変換すること。
        # 目的: 管理ユーザー操作が広い共有contextではなく必要依存だけで動く境界を固定する。
        config = AppConfig(
            db_path=tmp_path / "chat.sqlite",
            data_dir=tmp_path,
            uploads_dir=tmp_path / "uploads",
            session_secret="session-secret",
            password_pepper="password-pepper",
        )
        runtime = init_usecase_runtime(config=config)

        context = admin_user_usecase_context()

        assert context.database == runtime.database
        assert context.password_pepper == "password-pepper"
        assert context.attachment_storage.uploads_dir == tmp_path / "uploads"
        assert not hasattr(context, "response_service")


def test_create_user_persists_trimmed_login_name_and_password_hash(
    tmp_path: Path,
) -> None:
    # 観点: user作成ユースケースがlogin_name整形とパスワード保存形式を担うこと。
    # 目的: routeが整形やハッシュ詳細を持たずにuser作成を委譲できるようにする。
    context = _context(tmp_path)
    database = context.database

    created = create_user(
        login_name="  user1  ", password="pass123", is_admin=True, context=context
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
        login_name="user1", password="pass123", is_admin=False, context=context
    )
    actor = create_user(
        login_name="admin", password="adminpass", is_admin=True, context=context
    )

    updated = update_user(
        user_id=created.id,
        login_name="  user1-updated  ",
        password="pass456",
        is_admin=True,
        actor=actor,
        context=context,
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
        login_name="user1", password="pass123", is_admin=False, context=context
    )
    actor = create_user(
        login_name="admin", password="adminpass", is_admin=True, context=context
    )

    suspended = suspend_user(user_id=created.id, actor=actor, context=context)

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
    uploads_dir = context.attachment_storage.uploads_dir
    created = create_user(
        login_name="user1", password="pass123", is_admin=False, context=context
    )
    actor = create_user(
        login_name="admin", password="adminpass", is_admin=True, context=context
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

    deleted = delete_user(user_id=created.id, actor=actor, context=context)

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


def test_admin_user_usecase_preserves_the_last_active_admin(tmp_path: Path) -> None:
    # 観点: 最後の有効管理者の降格・休止・削除をUsecaseが拒否すること。
    # 目的: HTTP Routeを経由しない管理操作でも復旧不能な状態を作らない。
    context = _context(tmp_path)
    actor = create_user(
        login_name="admin", password="adminpass", is_admin=True, context=context
    )

    with pytest.raises(LastActiveAdminError):
        update_user(
            user_id=actor.id,
            login_name="admin",
            password="",
            is_admin=False,
            actor=actor,
            context=context,
        )
    with pytest.raises(CannotModifyCurrentAdminError):
        suspend_user(user_id=actor.id, actor=actor, context=context)
    with pytest.raises(CannotModifyCurrentAdminError):
        delete_user(user_id=actor.id, actor=actor, context=context)


def test_admin_user_usecase_rejects_self_suspend_and_delete_with_another_admin(
    tmp_path: Path,
) -> None:
    # 観点: 有効管理者が複数いてもactor自身の休止・削除を拒否すること。
    # 目的: 既存の自己ロックアウト防止規則をUsecaseの認可として固定する。
    context = _context(tmp_path)
    actor = create_user(
        login_name="admin", password="adminpass", is_admin=True, context=context
    )
    create_user(login_name="other", password="otherpass", is_admin=True, context=context)

    with pytest.raises(CannotModifyCurrentAdminError):
        suspend_user(user_id=actor.id, actor=actor, context=context)
    with pytest.raises(CannotModifyCurrentAdminError):
        delete_user(user_id=actor.id, actor=actor, context=context)


def test_admin_user_usecase_serializes_concurrent_last_admin_transitions(
    tmp_path: Path,
) -> None:
    # 観点: 2件の同時降格が有効管理者0人を作らないこと。
    # 目的: BEGIN IMMEDIATEとRepository条件判定の競合耐性をUsecase近接で固定する。
    context = _context(tmp_path)
    first = create_user(
        login_name="first", password="firstpass", is_admin=True, context=context
    )
    second = create_user(
        login_name="second", password="secondpass", is_admin=True, context=context
    )

    def demote(actor: User) -> str:
        try:
            update_user(
                user_id=actor.id,
                login_name=actor.login_name,
                password="",
                is_admin=False,
                actor=actor,
                context=context,
            )
        except LastActiveAdminError:
            return "rejected"
        return "updated"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(demote, (first, second)))

    with context.database.connect() as conn:
        active_admins = AuthRepository(conn).list_users()

    assert sorted(results) == ["rejected", "updated"]
    assert sum(user.is_admin and user.suspended_at is None for user in active_admins) == 1


def _context(tmp_path: Path) -> AdminUserUsecaseContext:
    """admin user ユースケース用のcontextを初期化して返す。

    Args:
        tmp_path: テストごとの一時ディレクトリ。

    Returns:
        初期化済みDatabase、固定pepper、添付保存境界を持つcontext。

    admin user ユースケースが必要とする依存だけで検証できるようにする。
    """
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()
    uploads_dir = tmp_path / "uploads"
    return AdminUserUsecaseContext(
        database=database,
        password_pepper="pepper",
        attachment_storage=AttachmentStorage(uploads_dir),
    )
