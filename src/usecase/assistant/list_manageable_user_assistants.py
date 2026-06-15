"""管理可能な UserAssistant 一覧取得ユースケースを担当する。"""

from ...infrastructure import UserAssistantRepository
from ...models import User, UserAssistant
from . import AssistantUsecaseContext, assistant_usecase_context


def list_manageable_user_assistants(
    actor: User, context: AssistantUsecaseContext | None = None
) -> list[UserAssistant]:
    """現在ユーザーが管理できる UserAssistant 一覧を返す。

    Args:
        actor: 一覧を見るユーザー。

    Returns:
        管理者なら全件、通常ユーザーなら所有分だけの UserAssistant 一覧。
    """
    ctx = context if context is not None else assistant_usecase_context()
    with ctx.database.connect() as conn:
        repo = UserAssistantRepository(conn)
        if actor.is_admin:
            return repo.list_active()
        return repo.list_by_owner(actor.id)
