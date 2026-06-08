"""認証チャレンジユースケースの責務を検証する。"""

from pathlib import Path

from src.infrastructure import AttachmentStorage, AuthRepository, Database
from src.usecase.admin_user.bootstrap_admin import bootstrap_admin
from src.usecase.auth import challenge
from src.usecase.context import UsecaseContext
from src.usecase.test_support import FakeResponseStarter


def test_auth_challenge_returns_user_only_for_valid_password(tmp_path: Path) -> None:
    # 観点: 正しいパスワードだけログインユーザーとして認証されること。
    # 目的: presentation が認証判断やハッシュ照合の詳細を知らずに usecase へ委譲できる境界を固定する。
    context = _context(tmp_path)
    bootstrap_admin(context, login_name="admin", password="adminpass")

    authenticated = challenge(context, login_name="admin", password="adminpass")
    rejected = challenge(context, login_name="admin", password="wrong")

    assert authenticated is not None
    assert authenticated.login_name == "admin"
    assert rejected is None


def test_auth_challenge_rejects_suspended_user(tmp_path: Path) -> None:
    # 観点: 休止中ユーザーは正しいパスワードでも認証されないこと。
    # 目的: ログイン可否の業務判断が repository ではなく usecase にあることを固定する。
    context = _context(tmp_path)
    created = bootstrap_admin(context, login_name="admin", password="adminpass")

    with context.database.connect() as conn:
        AuthRepository(conn).suspend_user(created.id)
        conn.commit()

    assert challenge(context, login_name="admin", password="adminpass") is None


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
