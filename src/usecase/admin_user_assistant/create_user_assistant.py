"""admin user assistant 作成ユースケースを担当する。"""


from ...infrastructure import BaseAssistantRepository, UserAssistantRepository
from ...models import AssistantVisibility, User, UserAssistant, UserInputError
from ..assistant._support import (
    new_user_assistant,
    require_admin,
    validate_user_fields,
)
from . import AdminUserAssistantUsecaseContext, admin_user_assistant_usecase_context


def create_user_assistant(
    *,
    actor: User,
    base_assistant_id: str | None,
    name: str,
    description: str,
    user_prompts: list[str],
    visibility: AssistantVisibility,
    context: AdminUserAssistantUsecaseContext | None = None,
) -> UserAssistant:
    """admin が所有する UserAssistant を作成する。

    Args:
        actor: 作成者である管理者。
        base_assistant_id: 元になる BaseAssistant ID。
        name: 表示名。
        description: 説明。
        user_prompts: 追加入力指示。
        visibility: 公開範囲。

    Returns:
        作成した UserAssistant。

    admin 管理画面の作成処理を user 向け usecase に依存せず独立して扱うため。
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
        if base_assistant_id is None or base_repo.get(base_assistant_id) is None:
            raise UserInputError("base assistant is required")
        assistant = UserAssistantRepository(conn).save(
            new_user_assistant(
                actor=actor,
                base_assistant_id=base_assistant_id,
                name=name,
                description=description,
                user_prompts=user_prompts,
                visibility=visibility,
            )
        )
        conn.commit()
        return assistant
