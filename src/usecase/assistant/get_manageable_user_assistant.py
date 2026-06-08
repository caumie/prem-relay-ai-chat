"""管理可能な UserAssistant 取得ユースケースを担当する。"""

from ...infrastructure import UserAssistantRepository
from ...models import User, UserAssistant
from ._support import can_manage_user_assistant
from ..context import UsecaseContext
from .errors import AssistantUsecaseError


def get_manageable_user_assistant(
    context: UsecaseContext,
    *,
    actor: User,
    user_assistant_id: str,
) -> UserAssistant:
    """現在ユーザーが編集できる UserAssistant を取得する。

    Args:
        actor: 操作中のユーザー。
        user_assistant_id: 対象 UserAssistant ID。

    Returns:
        編集可能な UserAssistant。
    """
    with context.database.connect() as conn:
        assistant = UserAssistantRepository(conn).get(user_assistant_id)
    if assistant is None:
        raise AssistantUsecaseError("user assistant not found")
    if not can_manage_user_assistant(actor=actor, assistant=assistant):
        raise AssistantUsecaseError("user assistant is not manageable")
    return assistant
