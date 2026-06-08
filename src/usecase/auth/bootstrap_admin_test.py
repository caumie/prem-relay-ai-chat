"""初期管理者作成ユースケースの責務を検証する。"""

from pathlib import Path

from src.infrastructure import AttachmentStorage, Database
from src.usecase.admin_user.bootstrap_admin import bootstrap_admin
from src.usecase.auth import challenge
from src.usecase.context import UsecaseContext
from src.usecase.test_support import FakeResponseStarter


def test_bootstrap_admin_creates_user_once(tmp_path: Path) -> None:
    # 観点: 起動時の初期管理者作成が何度呼ばれても重複しないこと。
    # 目的: アプリ起動処理が認証テーブルの詳細を直接扱わない境界を固定する。
    context = _context(tmp_path)

    first = bootstrap_admin(context, login_name="admin", password="adminpass")
    second = bootstrap_admin(context, login_name="admin", password="adminpass")

    with context.database.connect() as conn:
        count = conn.execute("select count(*) from active_users").fetchone()[0]

    assert first == second
    assert count == 1


def test_bootstrap_admin_stores_password_in_auth_challenge_format(
    tmp_path: Path,
) -> None:
    # 観点: bootstrap で作ったユーザーが challenge から認証できること。
    # 目的: ユースケース分解後も保存形式と認証形式が一致することを固定する。
    context = _context(tmp_path)
    bootstrap_admin(context, login_name="admin", password="adminpass")

    authenticated = challenge(context, login_name="admin", password="adminpass")

    assert authenticated is not None


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
