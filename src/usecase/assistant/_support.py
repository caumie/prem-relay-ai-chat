"""ユーザー向け assistant ユースケース間で共有する補助処理を定義する。"""

from dataclasses import replace
from uuid import uuid4

from ...config import connection_provider_by_id
from ...models import (
    AssistantConfigValue,
    AssistantVisibility,
    BaseAssistant,
    ConnectionProvider,
    ResolvedAssistant,
    User,
    UserAssistant,
    UserInputError,
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
