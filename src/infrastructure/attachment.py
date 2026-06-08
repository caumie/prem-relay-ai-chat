
"""添付ファイルmetadata集約の永続化を担当する。"""

import sqlite3

from ..models import Attachment
from .common import parse_dt


def model_from_row(row: sqlite3.Row) -> Attachment:
    return Attachment(
        id=row["id"],
        user_id=int(row["user_id"]),
        original_filename=row["original_filename"],
        stored_path=row["stored_path"],
        content_type=row["content_type"],
        size_bytes=int(row["size_bytes"]),
        sha256=row["sha256"],
        created_at=parse_dt(row["created_at"]),
    )


def row_from_model(attachment: Attachment) -> dict[str, object]:
    return dict(
        id=attachment.id,
        user_id=attachment.user_id,
        original_filename=attachment.original_filename,
        stored_path=attachment.stored_path,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        sha256=attachment.sha256,
        created_at=attachment.created_at.isoformat(),
    )


def id_filter_values(
    values: list[str],
    *,
    prefix: str,
) -> tuple[str, dict[str, object]]:
    names: list[str] = []
    params: dict[str, object] = {}
    for index, value in enumerate(values):
        key = f"{prefix}_{index}"
        names.append(f":{key}")
        params[key] = value
    return ", ".join(names), params


class AttachmentRepository:
    """Attachment metadataの保存・取得・削除を担当する。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(self, attachment: Attachment) -> Attachment:
        self.conn.execute(
            """
            insert into attachments(
                id,
                user_id,
                original_filename,
                stored_path,
                content_type,
                size_bytes,
                sha256,
                created_at
            )
            values(
                :id,
                :user_id,
                :original_filename,
                :stored_path,
                :content_type,
                :size_bytes,
                :sha256,
                :created_at
            )
            """,
            row_from_model(attachment),
        )
        return attachment

    def get_for_user(self, *, attachment_id: str, user_id: int) -> Attachment | None:
        row = self.conn.execute(
            """
            select * from
                attachments
            where
                    id = :id
                and user_id = :user_id
            """,
            dict(
                id=attachment_id,
                user_id=user_id,
            ),
        ).fetchone()
        return model_from_row(row) if row else None

    def list_by_ids_for_user(
        self, *, attachment_ids: list[str], user_id: int
    ) -> list[Attachment]:
        if not attachment_ids:
            return []
        placeholders, id_params = id_filter_values(
            attachment_ids, prefix="attachment_id"
        )
        rows = self.conn.execute(
            f"""
            select * from
                attachments
            where
                    user_id = :user_id
                and id in ({placeholders})
            order by
                created_at asc
            """,
            dict(user_id=user_id, **id_params),
        ).fetchall()
        return [model_from_row(row) for row in rows]

    def list_by_user(self, user_id: int) -> list[Attachment]:
        rows = self.conn.execute(
            """
            select * from
                attachments
            where
                user_id = :user_id
            order by
                created_at desc
            """,
            dict(user_id=user_id),
        ).fetchall()
        return [model_from_row(row) for row in rows]

    def physical_delete_by_user(self, user_id: int) -> int:
        """
        物理削除はDBのmetadataだけを消し、実ファイル削除は別境界に任せる。
        """
        cursor = self.conn.execute(
            """
            delete from
                attachments
            where
                user_id = :user_id
            """,
            dict(user_id=user_id),
        )
        return cursor.rowcount


__all__ = ["AttachmentRepository"]
