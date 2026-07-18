"""AuthRepositoryの保存・更新・削除責務を検証する。"""

from dataclasses import replace
from pathlib import Path

from src.infrastructure import AuthRepository, Database


def test_auth_repository_saves_updates_suspends_and_deletes_user(
    tmp_path: Path,
) -> None:
    # 観点: ユーザーをDB採番で作成・更新し、休止と物理削除ができること。
    # 目的: 認証Repositoryが未採番IDを受け取らずCRUDの永続化責務を担う境界を固定する。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        repo = AuthRepository(conn)
        admin = repo.create(
            login_name="admin",
            is_admin=True,
            password_hash="hash-admin",
        )
        user = repo.create(
            login_name="user",
            is_admin=False,
            password_hash="hash-user",
        )
        updated = repo.update(
            replace(user, login_name="member", is_admin=True),
            password_hash="hash-member",
        )
        suspended = repo.suspend_user(user.id)
        deleted = repo.delete_user(user.id)
        deleted_user = conn.execute(
            "select login_name from deleted_users where login_name = ?",
            ("member",),
        ).fetchone()
        conn.commit()

    assert admin.is_admin is True
    assert updated.login_name == "member"
    assert updated.is_admin is True
    assert suspended is True
    assert deleted is True
    assert deleted_user is not None


def test_auth_repository_delete_condition_keeps_the_last_active_admin(
    tmp_path: Path,
) -> None:
    # 観点: 条件付きDELETEが最後の有効管理者を削除しないこと。
    # 目的: Usecaseの確認漏れや競合があってもRepository境界で管理者を残す。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        repo = AuthRepository(conn)
        admin = repo.create(
            login_name="admin",
            is_admin=True,
            password_hash="hash-admin",
        )

        assert repo.delete_user(admin.id) is False
        assert repo.get_user(admin.id) == admin


def test_auth_repository_allows_admin_transition_when_another_active_admin_exists(
    tmp_path: Path,
) -> None:
    # 観点: 対象以外の有効管理者がいる場合は管理者遷移を許可すること。
    # 目的: 管理者の交代や冗長構成を通常操作として利用できることを固定する。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        repo = AuthRepository(conn)
        first = repo.create(login_name="first", is_admin=True, password_hash="hash")
        second = repo.create(login_name="second", is_admin=True, password_hash="hash")
        third = repo.create(login_name="third", is_admin=True, password_hash="hash")

        updated = repo.update(replace(first, is_admin=False))
        suspended = repo.suspend_user(second.id)

    assert updated.is_admin is False
    assert suspended is True
    assert third.is_admin is True


def test_auth_repository_owns_initial_setup_completion_state(tmp_path: Path) -> None:
    # 観点: 初期セットアップ完了状態をAuthRepositoryが一度だけ保存できること。
    # 目的: 管理者状態と同じ永続化境界でセットアップ完了を管理する。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        repo = AuthRepository(conn)
        assert repo.is_initial_setup_completed() is False
        repo.mark_initial_setup_completed()
        repo.mark_initial_setup_completed()
        conn.commit()

    with database.connect() as conn:
        repo = AuthRepository(conn)
        assert repo.is_initial_setup_completed() is True
        count = conn.execute(
            "select count(*) from initial_setup_state"
        ).fetchone()[0]

    assert count == 1
