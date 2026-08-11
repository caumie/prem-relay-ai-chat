"""admin base assistant 更新ユースケースを担当する。"""

from ...infrastructure import BaseAssistantRepository
from ...models import (
    AssistantGenerationConfig,
    BaseAssistant,
    User,
)
from ..assistant._support import (
    build_base_assistant,
    require_admin,
    validate_base_fields,
)
from ..assistant.errors import AssistantUsecaseError
from . import AdminBaseAssistantUsecaseContext, admin_base_assistant_usecase_context


def update_base_assistant(
    *,
    actor: User,
    base_assistant_id: str,
    name: str,
    description: str,
    system_prompt: str,
    user_prompts: list[str],
    connection_provider_id: str,
    model: str,
    max_history_messages: int,
    allow_file_upload: bool,
    generation_config: AssistantGenerationConfig,
    allowed_file_extensions: list[str] | None = None,
    context: AdminBaseAssistantUsecaseContext | None = None,
) -> BaseAssistant:
    """管理者入力を検証し、既存 BaseAssistant を更新して返す。

    Args:
        actor: 操作中のユーザー。
        base_assistant_id: 更新対象 ID。
        name: 表示名。
        description: 説明。
        system_prompt: システム指示。
        user_prompts: 追加入力指示。
        connection_provider_id: 接続先 ID。
        model: モデル名。
        max_history_messages: 履歴件数上限。
        allow_file_upload: 添付許可フラグ。
        generation_config: 生成設定。
        allowed_file_extensions: 添付許可時に受け付ける拡張子一覧。

    Returns:
        更新した BaseAssistant。

    編集画面から渡された入力だけで更新処理を独立して完結させるため。
    """
    ctx = context if context is not None else admin_base_assistant_usecase_context()
    require_admin(actor)
    providers = ctx.load_connection_providers()
    validate_base_fields(
        providers=providers,
        connection_provider_id=connection_provider_id,
        name=name,
        model=model,
        max_history_messages=max_history_messages,
    )
    with ctx.database.connect() as conn:
        repo = BaseAssistantRepository(conn)
        if repo.get(base_assistant_id) is None:
            raise AssistantUsecaseError("base assistant not found")
        updated = repo.update(
            build_base_assistant(
                assistant_id=base_assistant_id,
                name=name,
                description=description,
                system_prompt=system_prompt,
                user_prompts=user_prompts,
                connection_provider_id=connection_provider_id,
                model=model,
                generation_config=generation_config,
                max_history_messages=max_history_messages,
                allow_file_upload=allow_file_upload,
                allowed_file_extensions=allowed_file_extensions,
            )
        )
        conn.commit()
        return updated
