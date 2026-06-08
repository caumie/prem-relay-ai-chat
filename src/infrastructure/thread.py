
"""チャットThread集約の永続化を担当する。"""

import sqlite3

from ..models import Thread
from .common import parse_dt, utcnow


def model_from_row(row: sqlite3.Row) -> Thread:
    return Thread(
        id=row["id"],
        user_id=int(row["user_id"]),
        title=row["title"],
        created_at=parse_dt(row["created_at"]),
        updated_at=parse_dt(row["updated_at"]),
        deleted_at=parse_dt(row["deleted_at"]) if row["deleted_at"] else None,
    )


def row_from_model(thread: Thread) -> dict[str, object]:
    return dict(
        id=thread.id,
        user_id=thread.user_id,
        title=thread.title,
        created_at=thread.created_at.isoformat(),
        updated_at=thread.updated_at.isoformat(),
        deleted_at=thread.deleted_at.isoformat() if thread.deleted_at else None,
    )


class ThreadRepository:
    """Threadの保存・取得・削除を担当する。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list_by_user(self, user_id: int) -> list[Thread]:
        rows = self.conn.execute(
            """
            select * from
                threads
            where
                    user_id = :user_id
                and deleted_at is null
            order by
                updated_at desc
            """,
            dict(user_id=user_id),
        ).fetchall()
        return [model_from_row(row) for row in rows]

    def save(self, thread: Thread) -> Thread:
        self.conn.execute(
            """
            insert into threads(
                id,
                user_id,
                title,
                created_at,
                updated_at,
                deleted_at
            )
            values(
                :id,
                :user_id,
                :title,
                :created_at,
                :updated_at,
                :deleted_at
            )
            """,
            row_from_model(thread),
        )
        return thread

    def get(self, thread_id: str, user_id: int) -> Thread | None:
        row = self.conn.execute(
            """
            select * from
                threads
            where
                    id = :id
                and user_id = :user_id
                and deleted_at is null
            """,
            dict(
                id=thread_id,
                user_id=user_id,
            ),
        ).fetchone()
        return model_from_row(row) if row else None

    def touch(self, thread_id: str) -> None:
        self.conn.execute(
            """
            update threads set
                updated_at = :updated_at
            where
                id = :id
            """,
            dict(
                id=thread_id,
                updated_at=utcnow().isoformat(),
            ),
        )

    def update(self, thread: Thread) -> Thread | None:
        row = row_from_model(thread)
        cursor = self.conn.execute(
            """
            update threads set
                title = :title,
                updated_at = :updated_at,
                deleted_at = :deleted_at
            where
                    id = :id
                and user_id = :user_id
                and deleted_at is null
            """,
            row,
        )
        if cursor.rowcount != 1:
            return None
        return self.get(thread.id, thread.user_id)

    def logical_delete(self, *, thread_id: str, user_id: int) -> bool:
        """
        削除は論理削除とし、通常の一覧と詳細からだけ外す。
        """
        now = utcnow().isoformat()
        cursor = self.conn.execute(
            """
            update threads set
                deleted_at = :deleted_at,
                updated_at = :updated_at
            where
                    id = :id
                and user_id = :user_id
                and deleted_at is null
            """,
            dict(
                id=thread_id,
                user_id=user_id,
                deleted_at=now,
                updated_at=now,
            ),
        )
        return cursor.rowcount == 1

    def physical_delete_by_user(self, user_id: int) -> int:
        """
        ユーザー物理削除では、所有Threadも配下メッセージごと消す。
        """
        cursor = self.conn.execute(
            """
            delete from
                threads
            where
                user_id = :user_id
            """,
            dict(user_id=user_id),
        )
        return cursor.rowcount


__all__ = ["ThreadRepository"]
