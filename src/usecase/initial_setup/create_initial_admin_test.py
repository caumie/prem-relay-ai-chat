"""初回セットアップユースケースの責務を検証する。"""

from pathlib import Path


from src.config import AppConfig
from src.usecase.auth import AuthUsecaseContext, challenge
from src.usecase.initial_setup import (
    InitialSetupUsecaseContext,
    create_initial_admin,
    initial_setup_usecase_context,
)
from src.infrastructure import AuthRepository, Database
from src.usecase.runtime import init_usecase_runtime


def test_initial_setup_context_uses_password_pepper_from_config(
    tmp_path: Path,
) -> None:
    # 観点: 初回セットアップcontextがpassword_pepper設定を利用すること。
    # 目的: 初期管理者のパスワードをsession_secretへ依存させない境界を固定する。
    config = AppConfig(
        db_path=tmp_path / "chat.sqlite",
        data_dir=tmp_path,
        uploads_dir=tmp_path / "uploads",
        session_secret="session-secret",
        password_pepper="password-pepper",
    )
    runtime = init_usecase_runtime(config=config)

    context = initial_setup_usecase_context()

    assert context == InitialSetupUsecaseContext(
        database=runtime.database,
        password_pepper="password-pepper",
    )


def test_create_initial_admin_persists_admin_and_auth_password(
    tmp_path: Path,
) -> None:
    # 観点: 初回管理者作成が管理者権限と認証可能なパスワード形式を保存すること。
    # 目的: セットアップ画面がhashやis_admin設定を持たずに作成処理を委譲できるようにする。
    context = _context(tmp_path)

    created = create_initial_admin(
        login_name="  owner  ",
        password="ownerpass",
        context=context,
    )
    authenticated = challenge(
        login_name="owner",
        password="ownerpass",
        context=AuthUsecaseContext(
            database=context.database,
            password_pepper=context.password_pepper,
        ),
    )

    assert created.login_name == "owner"
    assert created.is_admin is True
    assert authenticated == created


def test_create_initial_admin_uses_database_generated_user_id(
    tmp_path: Path,
) -> None:
    # 観点: 非管理者が先に存在しても、初回管理者にDB採番済みIDが返ること。
    # 目的: 初回管理者のIDを0や固定値とする誤った前提を排除する。
    context = _context(tmp_path)
    with context.database.connect() as conn:
        existing = AuthRepository(conn).create(
            login_name="member",
            is_admin=False,
            password_hash="member-hash",
        )
        conn.commit()

    created = create_initial_admin(
        login_name="owner",
        password="ownerpass",
        context=context,
    )

    assert created.id > existing.id


def _context(tmp_path: Path) -> InitialSetupUsecaseContext:
    """テスト用DBを初期化した初回セットアップcontextを返す。"""
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()
    return InitialSetupUsecaseContext(
        database=database,
        password_pepper="pepper",
    )
