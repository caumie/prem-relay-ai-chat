"""AuthRepositoryの保存・更新・削除責務を検証する。"""

from dataclasses import replace
from pathlib import Path

from src.auth_password import hash_password, verify_password
from src.models import User
from src.infrastructure import AuthRepository, Database


def test_auth_repository_saves_updates_suspends_and_deletes_user(
    tmp_path: Path,
) -> None:
    # 観点: Userモデルを保存・更新し、休止と物理削除ができること。
    # 目的: 認証Repositoryが永続化責務だけを持つCRUD境界をモデル入力で固定する。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        repo = AuthRepository(conn)
        admin = repo.save(
            User(id=0, login_name="admin", is_admin=True),
            password_hash="hash-admin",
        )
        user = repo.save(User(id=0, login_name="user"), password_hash="hash-user")
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


def test_auth_repository_stores_salted_hashlib_password_hash(
    tmp_path: Path,
) -> None:
    # 観点: 認証Repositoryに保存したパスワードハッシュがsalt付き形式で検証できること。
    # 目的: user永続化が平文ではなく認証境界の検証可能なhash文字列を保存する契約を固定する。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        AuthRepository(conn).save(
            User(id=0, login_name="admin", is_admin=True),
            password_hash=hash_password("adminpass", "pepper"),
        )
        conn.commit()

    with database.connect() as conn:
        password_hash = conn.execute(
            "select password_hash from active_users where login_name = ?",
            ("admin",),
        ).fetchone()[0]

    parts = password_hash.split("$")
    assert parts[0] == "pbkdf2_sha256"
    assert len(parts) == 4
    assert verify_password("adminpass", password_hash, "pepper") is True
    assert verify_password("wrongpass", password_hash, "pepper") is False
