"""admin user assistant 削除ユースケースを担当する。"""

from ...infrastructure import UserAssistantRepository
from ...models import User
from ..assistant.errors import AssistantUsecaseError
from ..context import UsecaseContext


def delete_user_assistant(
    context: UsecaseContext, *, actor: User, user_assistant_id: str
) -> bool:
    """admin が対象 UserAssistant を論理削除する。

    Args:
        actor: 操作中の管理者。
        user_assistant_id: 対象 UserAssistant ID。

    Returns:
        削除できたら True。

    admin 管理画面から任意の user assistant を削除できるようにするため。
    """
    _require_admin(actor)
    with context.database.connect() as conn:
        repo = UserAssistantRepository(conn)
        if repo.get(user_assistant_id) is None:
            raise AssistantUsecaseError("user assistant not found")
        deleted = repo.logical_delete(user_assistant_id=user_assistant_id)
        conn.commit()
        return deleted


def _require_admin(actor: User) -> None:
    if not actor.is_admin:
        raise AssistantUsecaseError("admin required")
