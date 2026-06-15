"""admin base assistant 更新ユースケースを担当する。"""

from ...config import connection_provider_by_id
from ...infrastructure import BaseAssistantRepository
from ...models import (
    AssistantGenerationConfig,
    BaseAssistant,
    ConnectionProvider,
    User,
    UserInputError,
    default_assistant_file_extensions,
    normalize_file_extensions,
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
    _require_admin(actor)
    providers = ctx.load_connection_providers()
    _validate_fields(
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
            BaseAssistant(
                id=base_assistant_id,
                name=name.strip(),
                description=description.strip(),
                system_prompt=system_prompt.strip(),
                user_prompts=_clean_prompts(user_prompts),
                connection_provider_id=connection_provider_id,
                model=model.strip(),
                generation_config=generation_config,
                max_history_messages=max_history_messages,
                allow_file_upload=allow_file_upload,
                allowed_file_extensions=_clean_file_extensions(
                    allowed_file_extensions
                ),
            )
        )
        conn.commit()
        return updated


def _require_admin(actor: User) -> None:
    if not actor.is_admin:
        raise AssistantUsecaseError("admin required")


def _clean_prompts(prompts: list[str]) -> list[str]:
    return [prompt.strip() for prompt in prompts if prompt.strip()]


def _clean_file_extensions(extensions: list[str] | None) -> list[str]:
    """入力拡張子を正規化し、未指定ならBaseAssistant既定値を返す。

    Args:
        extensions: フォームやテストから渡された拡張子一覧。

    Returns:
        保存できるdotなし小文字の拡張子一覧。
    """
    normalized = normalize_file_extensions(extensions or [])
    return normalized or default_assistant_file_extensions()


def _validate_fields(
    *,
    providers: list[ConnectionProvider],
    connection_provider_id: str,
    name: str,
    model: str,
    max_history_messages: int,
) -> None:
    if not name.strip():
        raise UserInputError("name is required")
    if not model.strip():
        raise UserInputError("model is required")
    if max_history_messages <= 0:
        raise UserInputError("max_history_messages must be positive")
    provider = connection_provider_by_id(providers, connection_provider_id)
    if provider is None:
        raise UserInputError("connection provider is required")
    if provider.allowed_models and model.strip() not in provider.allowed_models:
        raise UserInputError("model is not allowed for this provider")
