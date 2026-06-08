"""UserAssistantRepositoryの保存・公開範囲責務を検証する。"""

import sqlite3
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from src.auth_password import hash_password
from src.models import (
    AssistantGenerationConfig,
    AssistantVisibility,
    BaseAssistant,
    User,
    UserAssistant,
)
from src.infrastructure import (
    AuthRepository,
    BaseAssistantRepository,
    Database,
    UserAssistantRepository,
)


def test_user_assistant_repository_saves_updates_and_lists_available_models(
    tmp_path: Path,
) -> None:
    # 観点: UserAssistantモデルを保存し、更新と利用候補取得ができること。
    # 目的: 個人アシスタント設定の保存境界と公開範囲規則を固定する。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    with database.connect() as conn:
        user = save_user(conn, "pepper", "user", "userpass")
        other = save_user(conn, "pepper", "other", "otherpass")
        base = save_base_assistant(
            conn,
            name="Base",
            description="base",
            system_prompt="system",
            user_prompts=["base prompt"],
            connection_provider_id="openai",
            model="gpt-5",
            generation_config={"temperature": 0.2},
            max_history_messages=20,
            allow_file_upload=True,
        )
        repo = UserAssistantRepository(conn)
        owned = save_user_assistant(
            conn,
            base_assistant_id=base.id,
            owner_user_id=user.id,
            name="Owned",
            description="owned",
            user_prompts=["mine"],
            visibility="private",
        )
        updated = repo.update(replace(owned, name="Updated"))
        public = save_user_assistant(
            conn,
            base_assistant_id=base.id,
            owner_user_id=other.id,
            name="Public",
            description="public",
            user_prompts=["shared"],
            visibility="public",
        )
        available = repo.list_available(user.id)
        conn.commit()

    assert updated.name == "Updated"
    assert [assistant.id for assistant in available] == [
        public.id,
        updated.id,
    ]


def save_user(
    conn: sqlite3.Connection,
    password_pepper: str,
    login_name: str,
    password: str,
) -> User:
    return AuthRepository(conn).save(
        User(id=0, login_name=login_name),
        password_hash=hash_password(password, password_pepper),
    )


def save_base_assistant(
    conn: sqlite3.Connection,
    *,
    name: str,
    description: str,
    system_prompt: str,
    user_prompts: list[str],
    connection_provider_id: str,
    model: str,
    generation_config: AssistantGenerationConfig,
    max_history_messages: int,
    allow_file_upload: bool,
) -> BaseAssistant:
    return BaseAssistantRepository(conn).save(
        BaseAssistant(
            id=str(uuid4()),
            name=name,
            description=description,
            system_prompt=system_prompt,
            user_prompts=user_prompts,
            connection_provider_id=connection_provider_id,
            model=model,
            generation_config=generation_config,
            max_history_messages=max_history_messages,
            allow_file_upload=allow_file_upload,
        )
    )


def save_user_assistant(
    conn: sqlite3.Connection,
    *,
    base_assistant_id: str | None,
    owner_user_id: int,
    name: str,
    description: str,
    user_prompts: list[str],
    visibility: AssistantVisibility,
) -> UserAssistant:
    return UserAssistantRepository(conn).save(
        UserAssistant(
            id=str(uuid4()),
            base_assistant_id=base_assistant_id,
            owner_user_id=owner_user_id,
            name=name,
            description=description,
            user_prompts=user_prompts,
            visibility=visibility,
        )
    )
