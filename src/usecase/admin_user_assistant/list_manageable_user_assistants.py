"""admin user assistant 一覧取得ユースケースを担当する。"""

from ...infrastructure import UserAssistantRepository
from ...models import User, UserAssistant
from ..assistant.errors import AssistantUsecaseError
from . import AdminUserAssistantUsecaseContext, admin_user_assistant_usecase_context


def list_manageable_user_assistants(
    actor: User,
    context: AdminUserAssistantUsecaseContext | None = None,
) -> list[UserAssistant]:
    """admin が管理できる UserAssistant 一覧を返す。

    Args:
        actor: 一覧を見る管理者。

    Returns:
        未削除の UserAssistant 一覧。

    admin 管理画面では所有者に関係なく全件を扱えるようにするため。
    """
    ctx = context if context is not None else admin_user_assistant_usecase_context()
    _require_admin(actor)
    with ctx.database.connect() as conn:
        return UserAssistantRepository(conn).list_active()


def _require_admin(actor: User) -> None:
    if not actor.is_admin:
        raise AssistantUsecaseError("admin required")
