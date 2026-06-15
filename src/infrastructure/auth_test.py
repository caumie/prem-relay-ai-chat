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
