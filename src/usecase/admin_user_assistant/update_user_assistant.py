"""admin user assistant 更新ユースケースを担当する。"""


from ...infrastructure import BaseAssistantRepository, UserAssistantRepository
from ...models import AssistantVisibility, User, UserAssistant, UserInputError
from ..assistant._support import (
    require_admin,
    updated_user_assistant,
    validate_user_fields,
)
from ..assistant.errors import AssistantUsecaseError
from . import AdminUserAssistantUsecaseContext, admin_user_assistant_usecase_context


def update_user_assistant(
    *,
    actor: User,
    user_assistant_id: str,
    base_assistant_id: str | None,
    name: str,
    description: str,
    user_prompts: list[str],
    visibility: AssistantVisibility,
    context: AdminUserAssistantUsecaseContext | None = None,
) -> UserAssistant:
    """admin が任意の UserAssistant を更新する。

    Args:
        actor: 操作中の管理者。
        user_assistant_id: 更新対象 ID。
        base_assistant_id: 元になる BaseAssistant ID。
        name: 表示名。
        description: 説明。
        user_prompts: 追加入力指示。
        visibility: 公開範囲。

    Returns:
        更新した UserAssistant。

    admin 管理画面が対象所有者に依存せず更新できるようにするため。
    """
    ctx = context if context is not None else admin_user_assistant_usecase_context()
    require_admin(actor)
    validate_user_fields(
        base_assistant_id=base_assistant_id,
        name=name,
        visibility=visibility,
    )
    with ctx.database.connect() as conn:
        base_repo = BaseAssistantRepository(conn)
        user_repo = UserAssistantRepository(conn)
        assistant = user_repo.get(user_assistant_id)
        if assistant is None:
            raise AssistantUsecaseError("user assistant not found")
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
