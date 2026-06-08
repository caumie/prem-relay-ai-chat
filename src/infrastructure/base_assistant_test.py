"""BaseAssistantRepositoryの保存・更新責務を検証する。"""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from src.models import BaseAssistant
from src.infrastructure import Database, BaseAssistantRepository


def test_base_assistant_repository_saves_and_updates_model(tmp_path: Path) -> None:
    # 観点: Repositoryが個別パラメータではなくモデルを受け取って保存・更新すること。
    # 目的: モデル構築責務をCRUD保存処理から外し、保存境界を単純に保つ。
    database = Database(tmp_path / "chat.sqlite")
    database.initialize()

    assistant = BaseAssistant(
        id=str(uuid4()),
        name="Base",
        description="base",
        system_prompt="system",
        user_prompts=["prompt"],
        connection_provider_id="openai",
        model="gpt-5",
        generation_config={"temperature": 0.2},
        max_history_messages=20,
        allow_file_upload=True,
        allowed_file_extensions=["jpg", "jpeg", "png"],
    )

    with database.connect() as conn:
        repo = BaseAssistantRepository(conn)
        saved = repo.save(assistant)
        updated = repo.update(
            replace(
                saved,
                name="Updated",
                allow_file_upload=False,
                allowed_file_extensions=["pdf"],
            )
        )
        loaded = repo.get(saved.id)
        conn.commit()

    assert saved == assistant
    assert updated.name == "Updated"
    assert updated.allow_file_upload is False
    assert updated.allowed_file_extensions == ["pdf"]
    assert loaded == updated
