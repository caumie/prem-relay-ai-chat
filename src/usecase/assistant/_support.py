"""Assistantユースケース間で共有する補助処理を定義する。"""

from dataclasses import replace
from uuid import uuid4

from ...config import connection_provider_by_id
from ...models import (
    AssistantConfigValue,
    AssistantGenerationConfig,
    AssistantVisibility,
    BaseAssistant,
    ConnectionProvider,
    ResolvedAssistant,
    User,
    UserAssistant,
    UserInputError,
    default_assistant_file_extensions,
    normalize_file_extensions,
)
from .errors import AssistantUsecaseError


def clean_prompts(prompts: list[str]) -> list[str]:
    """フォーム由来の複数プロンプトから空欄を取り除く。

    Args:
        prompts: 入力欄ごとのプロンプト文字列。

    Returns:
        前後空白を除き、空文字を捨てたプロンプト一覧。
    """
    return [prompt.strip() for prompt in prompts if prompt.strip()]


def require_admin(actor: User) -> None:
    """管理者だけが実行できるAssistant操作でactorを検証する。

    Args:
        actor: 操作中のユーザー。

    Returns:
        None。

    Raises:
        AssistantUsecaseError: actorが管理者でない場合。

    管理者向けAssistantユースケースに同じ認可分岐を複製しないため。
    """
    if not actor.is_admin:
        raise AssistantUsecaseError("admin required")


def validate_base_fields(
    *,
    providers: list[ConnectionProvider],
    connection_provider_id: str,
    name: str,
    model: str,
    max_history_messages: int,
) -> None:
    """BaseAssistantの作成・更新に共通する入力を検証する。

    Args:
        providers: 選択可能な接続先一覧。
        connection_provider_id: 使用する接続先ID。
        name: Assistant表示名。
        model: 使用するモデル名。
        max_history_messages: LLMへ渡す履歴件数上限。

    Returns:
        None。

    Raises:
        UserInputError: 必須値、履歴件数、接続先、モデルのいずれかが不正な場合。

    作成と更新で同じProvider・モデル制約を別々に実装しないため。
    """
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


def normalize_file_extensions_or_default(
    extensions: list[str] | None,
) -> list[str]:
    """添付拡張子を正規化し、空ならAssistant既定値を返す。

    Args:
        extensions: 入力された拡張子一覧。

    Returns:
        dotなし小文字の拡張子一覧。

    BaseAssistantの作成と更新で同じ既定値処理を複製しないため。
    """
    normalized = normalize_file_extensions(extensions or [])
    return normalized or default_assistant_file_extensions()


def build_base_assistant(
    *,
    assistant_id: str,
    name: str,
    description: str,
    system_prompt: str,
    user_prompts: list[str],
    connection_provider_id: str,
    model: str,
    max_history_messages: int,
    allow_file_upload: bool,
    generation_config: AssistantGenerationConfig,
    allowed_file_extensions: list[str] | None,
) -> BaseAssistant:
    """入力値から保存前のBaseAssistantを構築する。

    Args:
        assistant_id: 新規または更新対象のID。
        name: 表示名。
        description: 説明。
        system_prompt: システム指示。
        user_prompts: 追加入力指示。
        connection_provider_id: 接続先ID。
        model: モデル名。
        max_history_messages: 履歴件数上限。
        allow_file_upload: 添付許可フラグ。
        generation_config: 生成設定。
        allowed_file_extensions: 添付許可拡張子。

    Returns:
        入力を正規化したBaseAssistant。

    作成と更新で同じモデル構築・入力整形処理を複製しないため。
    """
    return BaseAssistant(
        id=assistant_id,
        name=name.strip(),
        description=description.strip(),
        system_prompt=system_prompt.strip(),
        user_prompts=clean_prompts(user_prompts),
        connection_provider_id=connection_provider_id,
        model=model.strip(),
        generation_config=generation_config,
        max_history_messages=max_history_messages,
        allow_file_upload=allow_file_upload,
        allowed_file_extensions=normalize_file_extensions_or_default(
            allowed_file_extensions
        ),
    )

def validate_user_fields(
    *,
    base_assistant_id: str | None,
    name: str,
    visibility: AssistantVisibility,
) -> None:
    """UserAssistant 保存前に必須値を検証する。

    Args:
        base_assistant_id: 元になる BaseAssistant ID。
        name: 表示名。
        visibility: 公開範囲。

    Returns:
        None。
    """
    if base_assistant_id is None or not base_assistant_id.strip():
        raise UserInputError("base assistant is required")
    if not name.strip():
        raise UserInputError("name is required")
    if visibility not in ("private", "public"):
        raise UserInputError("visibility is required")


def can_manage_user_assistant(*, actor: User, assistant: UserAssistant) -> bool:
    """現在ユーザーが対象 UserAssistant を編集できるか判定する。

    Args:
        actor: 操作中のユーザー。
        assistant: 対象 UserAssistant。

    Returns:
        管理者または所有者なら True。
    """
    return actor.is_admin or assistant.owner_user_id == actor.id


def new_user_assistant(
    *,
    actor: User,
    base_assistant_id: str,
    name: str,
    description: str,
    user_prompts: list[str],
    visibility: AssistantVisibility,
) -> UserAssistant:
    """入力値から新しい UserAssistant を構築する。

    Args:
        actor: 作成者。
        base_assistant_id: 元になる BaseAssistant ID。
        name: 表示名。
        description: 説明。
        user_prompts: 追記プロンプト一覧。
        visibility: 公開範囲。

    Returns:
        保存前の UserAssistant。
    """
    return UserAssistant(
        id=str(uuid4()),
        base_assistant_id=base_assistant_id,
        owner_user_id=actor.id,
        name=name.strip(),
        description=description.strip(),
        user_prompts=clean_prompts(user_prompts),
        visibility=visibility,
    )


def updated_user_assistant(
    *,
    assistant: UserAssistant,
    base_assistant_id: str,
    name: str,
    description: str,
    user_prompts: list[str],
    visibility: AssistantVisibility,
) -> UserAssistant:
    """入力値から更新後の UserAssistant を構築する。

    Args:
        assistant: 更新前の UserAssistant。
        base_assistant_id: 元になる BaseAssistant ID。
        name: 表示名。
        description: 説明。
        user_prompts: 追記プロンプト一覧。
        visibility: 公開範囲。

    Returns:
        更新後の UserAssistant。
    """
    return replace(
        assistant,
        base_assistant_id=base_assistant_id,
        name=name.strip(),
        description=description.strip(),
        user_prompts=clean_prompts(user_prompts),
        visibility=visibility,
    )


def resolve_base(
    *,
    providers: list[ConnectionProvider],
    base: BaseAssistant,
    user_assistant: UserAssistant | None = None,
) -> ResolvedAssistant:
    """BaseAssistant と任意の UserAssistant を実行時 Assistant へ合成する。

    Args:
        providers: 利用可能な接続先定義一覧。
        base: 実行元の BaseAssistant。
        user_assistant: 上書き元の UserAssistant。

    Returns:
        接続先解決済みの ResolvedAssistant。
    """
    provider = connection_provider_by_id(providers, base.connection_provider_id)
    if provider is None:
        raise AssistantUsecaseError("connection provider is unavailable")
    config = dict(provider.default_options)
    config.update(base.generation_config)
    config["api_key"] = provider.api_key
    config["model"] = base.model
    config["allow_file_upload"] = base.allow_file_upload
    allowed_file_extensions: list[AssistantConfigValue] = list(
        base.allowed_file_extensions
    )
    config["allowed_file_extensions"] = allowed_file_extensions
    user_prompts = list(base.user_prompts)
    name = base.name
    description = base.description
    assistant_id = base.id
    if user_assistant is not None:
        user_prompts.extend(user_assistant.user_prompts)
        name = user_assistant.name
        description = user_assistant.description
        assistant_id = user_assistant.id
    return ResolvedAssistant(
        id=assistant_id,
        name=name,
        description=description,
        system_prompt=base.system_prompt,
        user_prompts=user_prompts,
        api_mode=provider.api_mode,
        base_url=provider.base_url,
        config=config,
        max_history_messages=base.max_history_messages,
    )
