"""UserAssistant 更新ユースケースを担当する。"""

from ...infrastructure import BaseAssistantRepository, UserAssistantRepository
from ...models import AssistantVisibility, User, UserAssistant, UserInputError
from ._support import (
    can_manage_user_assistant,
    updated_user_assistant,
    validate_user_fields,
)
from ..context import UsecaseContext
from .errors import AssistantUsecaseError


def update_user_assistant(
    context: UsecaseContext,
    *,
    actor: User,
    user_assistant_id: str,
    base_assistant_id: str | None,
    name: str,
    description: str,
    user_prompts: list[str],
    visibility: AssistantVisibility,
) -> UserAssistant:
    """編集可能な UserAssistant を更新する。

    Args:
        actor: 操作中のユーザー。
        user_assistant_id: 更新対象 ID。
        base_assistant_id: 元になる BaseAssistant ID。
        name: 表示名。
        description: 説明。
        user_prompts: 追加入力指示。
        visibility: 公開範囲。

    Returns:
        更新した UserAssistant。
    """
    validate_user_fields(
        base_assistant_id=base_assistant_id,
        name=name,
        visibility=visibility,
    )
    with context.database.connect() as conn:
        base_repo = BaseAssistantRepository(conn)
        user_repo = UserAssistantRepository(conn)
        assistant = user_repo.get(user_assistant_id)
        if assistant is None:
            raise AssistantUsecaseError("user assistant not found")
        if not can_manage_user_assistant(actor=actor, assistant=assistant):
            raise AssistantUsecaseError("user assistant is not manageable")
        if base_assistant_id is None or base_repo.get(base_assistant_id) is None:
            raise UserInputError("base assistant is required")
        updated = user_repo.update(
            updated_user_assistant(
                assistant=assistant,
                base_assistant_id=base_assistant_id,
                name=name,
                description=description,
                user_prompts=user_prompts,
                visibility=visibility,
            )
        )
        conn.commit()
        return updated
