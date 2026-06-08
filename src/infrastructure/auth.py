
"""認証ユーザー集約の永続化を担当する。"""

import sqlite3

from ..models import User
from .common import parse_dt, utcnow


def model_from_row(row: sqlite3.Row) -> User:
    return User(
        id=int(row["id"]),
        login_name=row["login_name"],
        is_admin=bool(row["is_admin"]),
        suspended_at=parse_dt(row["suspended_at"]) if row["suspended_at"] else None,
    )


def row_from_model(
    user: User,
    *,
    password_hash: str,
    created_at: str | None = None,
    updated_at: str,
) -> dict[str, object]:
    row: dict[str, object] = dict(
        login_name=user.login_name,
        password_hash=password_hash,
        is_admin=1 if user.is_admin else 0,
        suspended_at=user.suspended_at.isoformat() if user.suspended_at else None,
        updated_at=updated_at,
    )
    if user.id > 0:
        row["id"] = user.id
    if created_at is not None:
        row["created_at"] = created_at
    return row


class AuthRepository:
    """Userの保存・認証・削除を担当する。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(self, user: User, *, password_hash: str) -> User:
        now = utcnow().isoformat()
        row = row_from_model(
            user,
            password_hash=password_hash,
            created_at=now,
            updated_at=now,
        )
        if user.id > 0:
            self.conn.execute(
                """
                insert into active_users(
                    id,
                    login_name,
                    password_hash,
                    is_admin,
                    suspended_at,
                    created_at,
                    updated_at
                )
                values(
                    :id,
                    :login_name,
                    :password_hash,
                    :is_admin,
                    :suspended_at,
                    :created_at,
                    :updated_at
                )
                """,
                row,
            )
            user_id = user.id
        else:
            cursor = self.conn.execute(
                """
                insert into active_users(
                    login_name,
                    password_hash,
                    is_admin,
                    suspended_at,
                    created_at,
                    updated_at
                )
                values(
                    :login_name,
                    :password_hash,
                    :is_admin,
                    :suspended_at,
                    :created_at,
                    :updated_at
                )
                """,
                row,
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create user")
            user_id = int(cursor.lastrowid)
        loaded = self.get_user(user_id)
        if loaded is None:
            raise RuntimeError("Failed to create user")
        return loaded

    def get_by_login_name(self, login_name: str) -> User | None:
        row = self.conn.execute(
            """
            select
                id,
                login_name,
                is_admin,
                suspended_at
            from
                active_users
            where
                login_name = :login_name
            """,
            dict(login_name=login_name),
        ).fetchone()
        return model_from_row(row) if row else None

    def get_user(self, user_id: int) -> User | None:
        row = self.conn.execute(
            """
            select
                id,
                login_name,
                is_admin,
                suspended_at
            from
                active_users
            where
                id = :id
            """,
            dict(id=user_id),
        ).fetchone()
        return model_from_row(row) if row else None

    def get_password_hash_by_login_name(self, login_name: str) -> str | None:
        row = self.conn.execute(
            """
            select
                password_hash
            from
                active_users
            where
                login_name = :login_name
            """,
            dict(login_name=login_name),
        ).fetchone()
        if row is None:
            return None
        value = row["password_hash"]
        return str(value)

    def list_users(self) -> list[User]:
        rows = self.conn.execute("""
            select
                id,
                login_name,
                is_admin,
                suspended_at
            from
                active_users
            order by
                id asc
            """).fetchall()
        return [model_from_row(row) for row in rows]

    def update(self, user: User, *, password_hash: str | None = None) -> User:
        existing = self.conn.execute(
            """
            select
                password_hash
            from
                active_users
            where
                id = :id
            """,
            dict(id=user.id),
        ).fetchone()
        if existing is None:
            raise RuntimeError("Failed to update user")
        row = row_from_model(
            user,
            password_hash=password_hash or str(existing["password_hash"]),
            updated_at=utcnow().isoformat(),
        )
        self.conn.execute(
            """
            update active_users set
                login_name = :login_name,
                password_hash = :password_hash,
                is_admin = :is_admin,
                suspended_at = :suspended_at,
                updated_at = :updated_at
            where
                id = :id
            """,
            row,
        )
        loaded = self.get_user(user.id)
        if loaded is None:
            raise RuntimeError("Failed to update user")
        return loaded

    def suspend_user(self, user_id: int) -> bool:
        return self._set_user_suspended(user_id, True)

    def _set_user_suspended(self, user_id: int, suspended: bool) -> bool:
        now = utcnow().isoformat()
        cursor = self.conn.execute(
            """
            update active_users set
                suspended_at = :suspended_at,
                updated_at = :updated_at
            where
                id = :id
            """,
            dict(
                id=user_id,
                suspended_at=now if suspended else None,
                updated_at=now,
            ),
        )
        return cursor.rowcount == 1

    def delete_user(self, user_id: int) -> bool:
        """
        削除は物理削除とし、ログイン名だけ deleted_users に退避する。
        """
        row = self.conn.execute(
            """
            select
                id,
                login_name
            from
                active_users
            where
                id = :id
            """,
            dict(id=user_id),
        ).fetchone()
        if row is None:
            return False
        now = utcnow().isoformat()
        self.conn.execute(
            """
            insert into deleted_users(
                login_name,
                deleted_at
            )
            values(
                :login_name,
                :deleted_at
            )
            """,
            dict(
                login_name=row["login_name"],
                deleted_at=now,
            ),
        )
        cursor = self.conn.execute(
            """
            delete from
                active_users
            where
                id = :id
            """,
            dict(id=user_id),
        )
        return cursor.rowcount == 1


__all__ = ["AuthRepository"]
