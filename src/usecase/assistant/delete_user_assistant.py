"""UserAssistant 削除ユースケースを担当する。"""

from ...infrastructure import UserAssistantRepository
from ...models import User
from ._support import can_manage_user_assistant
from ..context import UsecaseContext
from .errors import AssistantUsecaseError


def delete_user_assistant(
    context: UsecaseContext, *, actor: User, user_assistant_id: str
) -> bool:
    """編集可能な UserAssistant を論理削除する。

    Args:
        actor: 操作中のユーザー。
        user_assistant_id: 対象 UserAssistant ID。

    Returns:
        削除できたら True。
    """
    with context.database.connect() as conn:
        repo = UserAssistantRepository(conn)
        assistant = repo.get(user_assistant_id)
        if assistant is None:
            raise AssistantUsecaseError("user assistant not found")
        if not can_manage_user_assistant(actor=actor, assistant=assistant):
            raise AssistantUsecaseError("user assistant is not manageable")
        deleted = repo.logical_delete(user_assistant_id=user_assistant_id)
        conn.commit()
        return deleted
