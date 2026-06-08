"""管理可能な UserAssistant 一覧取得ユースケースを担当する。"""

from ...infrastructure import UserAssistantRepository
from ...models import User, UserAssistant
from ..context import UsecaseContext


def list_manageable_user_assistants(
    context: UsecaseContext, actor: User
) -> list[UserAssistant]:
    """現在ユーザーが管理できる UserAssistant 一覧を返す。

    Args:
        actor: 一覧を見るユーザー。

    Returns:
        管理者なら全件、通常ユーザーなら所有分だけの UserAssistant 一覧。
    """
    with context.database.connect() as conn:
        repo = UserAssistantRepository(conn)
        if actor.is_admin:
            return repo.list_active()
        return repo.list_by_owner(actor.id)
