"""admin user assistant 一覧取得ユースケースを担当する。"""

from ...infrastructure import UserAssistantRepository
from ...models import User, UserAssistant
from ..assistant.errors import AssistantUsecaseError
from ..context import UsecaseContext


def list_manageable_user_assistants(
    context: UsecaseContext, actor: User
) -> list[UserAssistant]:
    """admin が管理できる UserAssistant 一覧を返す。

    Args:
        actor: 一覧を見る管理者。

    Returns:
        未削除の UserAssistant 一覧。

    admin 管理画面では所有者に関係なく全件を扱えるようにするため。
    """
    _require_admin(actor)
    with context.database.connect() as conn:
        return UserAssistantRepository(conn).list_active()


def _require_admin(actor: User) -> None:
    if not actor.is_admin:
        raise AssistantUsecaseError("admin required")
