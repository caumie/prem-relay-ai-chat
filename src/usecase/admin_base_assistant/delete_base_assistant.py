"""admin base assistant 削除ユースケースを担当する。"""

from ...infrastructure import BaseAssistantRepository
from ...models import User
from ..assistant.errors import AssistantUsecaseError
from . import AdminBaseAssistantUsecaseContext, admin_base_assistant_usecase_context


def delete_base_assistant(
    *,
    actor: User,
    base_assistant_id: str,
    context: AdminBaseAssistantUsecaseContext | None = None,
) -> bool:
    """BaseAssistant を論理削除する。

    Args:
        actor: 操作中の管理者。
        base_assistant_id: 対象 BaseAssistant ID。

    Returns:
        削除できたら True。

    管理対象の base assistant を存在確認つきで削除するため。
    """
    ctx = context if context is not None else admin_base_assistant_usecase_context()
    _require_admin(actor)
    with ctx.database.connect() as conn:
        repo = BaseAssistantRepository(conn)
        if repo.get(base_assistant_id) is None:
            raise AssistantUsecaseError("base assistant not found")
        deleted = repo.logical_delete(base_assistant_id=base_assistant_id)
        conn.commit()
        return deleted


def _require_admin(actor: User) -> None:
    if not actor.is_admin:
        raise AssistantUsecaseError("admin required")
