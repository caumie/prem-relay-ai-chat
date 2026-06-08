"""現在ユーザー取得ユースケースの責務を検証する。"""

from pathlib import Path

from src.infrastructure import AttachmentStorage, AuthRepository, Database
from src.usecase.admin_user.bootstrap_admin import bootstrap_admin
from src.usecase.auth import get_current_user
from src.usecase.context import UsecaseContext
from src.usecase.test_support import FakeResponseStarter


def test_get_current_user_returns_none_for_missing_user(tmp_path: Path) -> None:
    # 観点: セッション内 user_id から現在ユーザーを取得でき、欠落時は None を返すこと。
    # 目的: presentation 層が認証状態の有無だけを扱える境界を固定する。
    context = _context(tmp_path)
    created = bootstrap_admin(context, login_name="admin", password="adminpass")

    assert get_current_user(context, user_id=created.id) == created
    assert get_current_user(context, user_id=9999) is None


def test_get_current_user_returns_none_for_suspended_user(tmp_path: Path) -> None:
    # 観点: 休止中ユーザーはセッションからも有効扱いにしないこと。
    # 目的: ログイン済みでも休止後はアクセスを止められる境界を固定する。
    context = _context(tmp_path)
    created = bootstrap_admin(context, login_name="admin", password="adminpass")

    with context.database.connect() as conn:
        AuthRepository(conn).suspend_user(created.id)
        conn.commit()

    assert get_current_user(context, user_id=created.id) is None


def _context(tmp_path: Path) -> UsecaseContext:
    """認証用のテストcontextを初期化して返す。"""
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
