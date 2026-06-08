
"""
BaseAssistantの永続化
BaseAssistantは管理者が作成・更新を行う
BaseAssistantをもとにしてUserAssistantを作成する
"""

import json
import sqlite3

from ..models import (
    BaseAssistant,
    normalize_file_extensions,
)
from .common import (
    parse_dt,
    utcnow,
)


def model_from_row(row: sqlite3.Row) -> BaseAssistant:
    generation_config = json.loads(row["generation_config_json"])
    user_prompts_json = json.loads(row["user_prompts_json"])
    # データを受けとる時点で、stripなどの前処理を入れておく。
    # 保存後は前処理済みのクリーンなデータが入る想定。
    user_prompts = [item.strip() for item in user_prompts_json if item.strip()]
    allowed_file_extensions_json = json.loads(row["allowed_file_extensions_json"])
    allowed_file_extensions = [
        item for item in allowed_file_extensions_json if isinstance(item, str)
    ]

    return BaseAssistant(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        system_prompt=row["system_prompt"],
        user_prompts=user_prompts,
        connection_provider_id=row["connection_provider_id"],
        model=row["model"],
        generation_config=generation_config,
        max_history_messages=int(row["max_history_messages"]),
        allow_file_upload=bool(row["allow_file_upload"]),
        allowed_file_extensions=normalize_file_extensions(allowed_file_extensions),
        deleted_at=parse_dt(row["deleted_at"]) if row["deleted_at"] else None,
    )


def row_from_model(
    assistant: BaseAssistant,
    *,
    created_at: str | None = None,
    updated_at: str,
) -> dict[str, object]:
    row: dict[str, object] = dict(
        id=assistant.id,
        name=assistant.name,
        description=assistant.description,
        system_prompt=assistant.system_prompt,
        user_prompts_json=json.dumps(
            assistant.user_prompts,
            ensure_ascii=False,
        ),
        connection_provider_id=assistant.connection_provider_id,
        model=assistant.model,
        generation_config_json=json.dumps(
            assistant.generation_config,
        ),
        max_history_messages=assistant.max_history_messages,
        allow_file_upload=1 if assistant.allow_file_upload else 0,
        allowed_file_extensions_json=json.dumps(
            assistant.allowed_file_extensions,
            ensure_ascii=False,
        ),
        updated_at=updated_at,
    )
    if created_at is not None:
        row["created_at"] = created_at
    return row


class BaseAssistantRepository:
    """管理者作成のBaseAssistant設定の保存・更新・取得を担当する。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(self, assistant: BaseAssistant) -> BaseAssistant:
        now = utcnow().isoformat()
        row = row_from_model(
            assistant,
            created_at=now,
            updated_at=now,
        )
        self.conn.execute(
            """
            insert into base_assistants(
                id, name, description, system_prompt, user_prompts_json,
                connection_provider_id, model, generation_config_json,
                max_history_messages, allow_file_upload,
                allowed_file_extensions_json,
                deleted_at, created_at, updated_at
            )
            values(
                :id, :name, :description, :system_prompt, :user_prompts_json,
                :connection_provider_id, :model, :generation_config_json,
                :max_history_messages, :allow_file_upload,
                :allowed_file_extensions_json,
                null, :created_at, :updated_at
            )
            """,
            row,
        )
        loaded = self.get(assistant.id)
        if loaded is None:
            raise RuntimeError("Failed to create base assistant")
        return loaded

    def update(self, assistant: BaseAssistant) -> BaseAssistant:
        row = row_from_model(
            assistant,
            updated_at=utcnow().isoformat(),
        )
        self.conn.execute(
            """
            update base_assistants set
                name = :name,
                description = :description,
                system_prompt = :system_prompt,
                user_prompts_json = :user_prompts_json,
                connection_provider_id = :connection_provider_id,
                model = :model,
                generation_config_json = :generation_config_json,
                max_history_messages = :max_history_messages,
                allow_file_upload = :allow_file_upload,
                allowed_file_extensions_json = :allowed_file_extensions_json,
                updated_at = :updated_at
             where
                    id = :id
                and deleted_at is null
            """,
            row,
        )
        loaded = self.get(assistant.id)
        if loaded is None:
            raise RuntimeError("Failed to update base assistant")
        return loaded

    def get(self, base_assistant_id: str) -> BaseAssistant | None:
        row = self.conn.execute(
            """
            select * from
                base_assistants
            where
                    id = :id
                and deleted_at is null
            """,
            dict(id=base_assistant_id),
        ).fetchone()
        return model_from_row(row) if row else None

    def list_active(self) -> list[BaseAssistant]:
        rows = self.conn.execute("""
            select * from
                base_assistants
            where
                deleted_at is null
            order by
                 name asc
                ,id asc
            """).fetchall()
        return [model_from_row(row) for row in rows]

    def logical_delete(self, *, base_assistant_id: str) -> bool:
        """
        削除は論理削除とし、deleted_atに削除日時を入れる。
        """
        now = utcnow().isoformat()
        cursor = self.conn.execute(
            """
            update base_assistants set
                deleted_at = :deleted_at,
                updated_at = :updated_at
            where
                    id = :id
                and deleted_at is null
            """,
            dict(
                id=base_assistant_id,
                deleted_at=now,
                updated_at=now,
            ),
        )
        return cursor.rowcount == 1
