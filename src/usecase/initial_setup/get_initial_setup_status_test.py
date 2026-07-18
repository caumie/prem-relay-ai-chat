"""初回セットアップユースケースの責務を検証する。"""

from pathlib import Path

import pytest

from src.usecase.initial_setup import (
    InitialAdminAlreadyExistsError,
    InitialSetupUsecaseContext,
    create_initial_admin,
    get_initial_setup_status,
)
from src.infrastructure import AuthRepository, Database


def test_get_initial_setup_status_allows_setup_when_admin_does_not_exist(
    tmp_path: Path,
) -> None:
    # 観点: 管理者が存在しないDBでは初回セットアップ可能と判定されること。
    # 目的: routeが永続化詳細を知らずに初回管理者作成画面の表示可否を判断できるようにする。
    context = _context(tmp_path)

    status = get_initial_setup_status(context=context)

    assert status.can_create_initial_admin is True


def test_create_initial_admin_rejects_when_admin_already_exists(
    tmp_path: Path,
) -> None:
    # 観点: 管理者作成後は初回セットアップが閉じること。
    # 目的: 未ログイン画面から管理者を追加作成できないセキュリティ境界を固定する。
    context = _context(tmp_path)
    create_initial_admin(
        login_name="owner",
        password="ownerpass",
        context=context,
    )

    with pytest.raises(InitialAdminAlreadyExistsError):
        create_initial_admin(
            login_name="second",
            password="secondpass",
            context=context,
        )

    status = get_initial_setup_status(context=context)
    with context.database.connect() as conn:
        users = AuthRepository(conn).list_users()

    assert status.can_create_initial_admin is False
    assert len(users) == 1


def test_setup_stays_closed_when_the_completed_admin_is_no_longer_active(
    tmp_path: Path,
) -> None:
    # 観点: 初期セットアップ完了後に管理者行が停止・削除されても再公開しないこと。
    # 目的: 管理者件数ではなく一度きりの完了状態で未認証導線を閉じる。
    context = _context(tmp_path)
    created = create_initial_admin(
        login_name="owner",
        password="ownerpass",
        context=context,
    )
    with context.database.transaction() as conn:
        conn.execute("delete from active_users where id = ?", (created.id,))

    status = get_initial_setup_status(context=context)

    assert status.can_create_initial_admin is False


def _context(tmp_path: Path) -> InitialSetupUsecaseContext:
    """テスト用DBを初期化した初回セットアップcontextを返す。"""
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()
    return InitialSetupUsecaseContext(
        database=database,
        password_pepper="pepper",
    )
