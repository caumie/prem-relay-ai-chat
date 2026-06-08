"""UserAssistant 作成ユースケースを担当する。"""

from ...infrastructure import BaseAssistantRepository, UserAssistantRepository
from ...models import AssistantVisibility, User, UserAssistant, UserInputError
from ._support import new_user_assistant, validate_user_fields
from ..context import UsecaseContext


def create_user_assistant(
    context: UsecaseContext,
    *,
    actor: User,
    base_assistant_id: str | None,
    name: str,
    description: str,
    user_prompts: list[str],
    visibility: AssistantVisibility,
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
    validate_user_fields(
        base_assistant_id=base_assistant_id,
        name=name,
        visibility=visibility,
    )
    with context.database.connect() as conn:
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
