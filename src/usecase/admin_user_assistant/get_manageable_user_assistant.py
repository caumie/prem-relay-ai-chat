"""admin user assistant 取得ユースケースを担当する。"""

from ...infrastructure import UserAssistantRepository
from ...models import User, UserAssistant
from ..assistant.errors import AssistantUsecaseError
from ..context import UsecaseContext


def get_manageable_user_assistant(
    context: UsecaseContext,
    *,
    actor: User,
    user_assistant_id: str,
) -> UserAssistant:
    """admin が編集できる UserAssistant を取得する。

    Args:
        actor: 操作中の管理者。
        user_assistant_id: 対象 UserAssistant ID。

    Returns:
        編集可能な UserAssistant。

    admin 管理画面が対象 assistant の存在確認込みで取得できるようにするため。
    """
    _require_admin(actor)
    with context.database.connect() as conn:
        assistant = UserAssistantRepository(conn).get(user_assistant_id)
    if assistant is None:
        raise AssistantUsecaseError("user assistant not found")
    return assistant


def _require_admin(actor: User) -> None:
    if not actor.is_admin:
        raise AssistantUsecaseError("admin required")
