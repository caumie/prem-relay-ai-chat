"""UserAssistant 作成ユースケースを担当する。"""

from ...infrastructure import BaseAssistantRepository, UserAssistantRepository
from ...models import AssistantVisibility, User, UserAssistant, UserInputError
from ._support import new_user_assistant, validate_user_fields
from . import AssistantUsecaseContext, assistant_usecase_context


def create_user_assistant(
    *,
    actor: User,
    base_assistant_id: str | None,
    name: str,
    description: str,
    user_prompts: list[str],
    visibility: AssistantVisibility,
    context: AssistantUsecaseContext | None = None,
) -> UserAssistant:
    """現在ユーザー所有の UserAssistant を作成する。

    Args:
        actor: 作成者。
        base_assistant_id: 元になる BaseAssistant ID。
        name: 表示名。
        description: 説明。
        user_prompts: 追加入力指示。
        visibility: 公開範囲。

    Returns:
        作成した UserAssistant。
    """
    ctx = context if context is not None else assistant_usecase_context()
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
