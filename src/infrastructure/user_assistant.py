"""ユーザー作成UserAssistant集約の永続化を担当する。"""

import json
import sqlite3

from ..models import UserAssistant
from .common import parse_dt, utcnow


def model_from_row(row: sqlite3.Row) -> UserAssistant:
    user_prompts_json = json.loads(row["user_prompts_json"])
    user_prompts = [item.strip() for item in user_prompts_json if item.strip()]
    return UserAssistant(
        id=row["id"],
        base_assistant_id=(
            row["base_assistant_id"] if row["base_assistant_id"] else None
        ),
        owner_user_id=int(row["owner_user_id"]),
        name=row["name"],
        description=row["description"],
        user_prompts=user_prompts,
        visibility="public" if row["visibility"] == "public" else "private",
        deleted_at=parse_dt(row["deleted_at"]) if row["deleted_at"] else None,
    )


def row_from_model(
    assistant: UserAssistant,
    *,
    created_at: str | None = None,
    updated_at: str,
) -> dict[str, object]:
    row: dict[str, object] = dict(
        id=assistant.id,
        base_assistant_id=assistant.base_assistant_id,
        owner_user_id=assistant.owner_user_id,
        name=assistant.name,
        description=assistant.description,
        user_prompts_json=json.dumps(
            assistant.user_prompts,
            ensure_ascii=False,
        ),
        visibility=assistant.visibility,
        updated_at=updated_at,
    )
    if created_at is not None:
        row["created_at"] = created_at
    return row


class UserAssistantRepository:
    """UserAssistantの保存・取得・削除を担当する。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(self, assistant: UserAssistant) -> UserAssistant:
        now = utcnow().isoformat()
        self.conn.execute(
            """
            insert into user_assistants(
                id,
                base_assistant_id,
                owner_user_id,
                name,
                description,
                user_prompts_json,
                visibility,
                deleted_at,
                created_at,
                updated_at
            )
            values(
                :id,
                :base_assistant_id,
                :owner_user_id,
                :name,
                :description,
                :user_prompts_json,
                :visibility,
                null,
                :created_at,
                :updated_at
            )
            """,
            row_from_model(
                assistant,
                created_at=now,
                updated_at=now,
            ),
        )
        loaded = self.get(assistant.id)
        if loaded is None:
            raise RuntimeError("Failed to create user assistant")
        return loaded

    def update(self, assistant: UserAssistant) -> UserAssistant:
        self.conn.execute(
            """
            update user_assistants set
                base_assistant_id = :base_assistant_id,
                name = :name,
                description = :description,
                user_prompts_json = :user_prompts_json,
                visibility = :visibility,
                updated_at = :updated_at
            where
                    id = :id
                and deleted_at is null
            """,
            row_from_model(
                assistant,
                updated_at=utcnow().isoformat(),
            ),
        )
        loaded = self.get(assistant.id)
        if loaded is None:
            raise RuntimeError("Failed to update user assistant")
        return loaded

    def get(self, user_assistant_id: str) -> UserAssistant | None:
        row = self.conn.execute(
            """
            select * from
                user_assistants
            where
                    id = :id
                and deleted_at is null
            """,
            dict(id=user_assistant_id),
        ).fetchone()
        return model_from_row(row) if row else None

    def list_active(self) -> list[UserAssistant]:
        rows = self.conn.execute("""
            select * from
                user_assistants
            where
                deleted_at is null
            order by
                 name asc
                ,id asc
            """).fetchall()
        return [model_from_row(row) for row in rows]

    def list_by_owner(self, user_id: int) -> list[UserAssistant]:
        rows = self.conn.execute(
            """
            select * from
                user_assistants
            where
                    deleted_at is null
                and owner_user_id = :owner_user_id
            order by
                 name asc
                ,id asc
            """,
            dict(owner_user_id=user_id),
        ).fetchall()
        return [model_from_row(row) for row in rows]

    def list_available(self, user_id: int) -> list[UserAssistant]:
        rows = self.conn.execute(
            """
            select * from
                user_assistants
            where
                    deleted_at is null
                and (
                        visibility = 'public'
                    or owner_user_id = :owner_user_id
                )
            order by
                 name asc
                ,id asc
            """,
            dict(owner_user_id=user_id),
        ).fetchall()
        return [model_from_row(row) for row in rows]

    def logical_delete(self, *, user_assistant_id: str) -> bool:
        """
        削除は論理削除とし、利用候補からだけ外す。
        """
        now = utcnow().isoformat()
        cursor = self.conn.execute(
            """
            update user_assistants set
                deleted_at = :deleted_at,
                updated_at = :updated_at
            where
                    id = :id
                and deleted_at is null
            """,
            dict(
                id=user_assistant_id,
                deleted_at=now,
                updated_at=now,
            ),
        )
        return cursor.rowcount == 1

    def physical_delete_by_owner(self, owner_user_id: int) -> int:
        """
        ユーザー物理削除では、所有UserAssistantも残さない。
        """
        cursor = self.conn.execute(
            """
            delete from
                user_assistants
            where
                owner_user_id = :owner_user_id
            """,
            dict(owner_user_id=owner_user_id),
        )
        return cursor.rowcount


__all__ = ["UserAssistantRepository"]
