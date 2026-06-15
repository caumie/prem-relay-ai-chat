"""admin base assistant 取得ユースケースを担当する。"""

from ...infrastructure import BaseAssistantRepository
from ...models import BaseAssistant
from ..assistant.errors import AssistantUsecaseError
from . import AdminBaseAssistantUsecaseContext, admin_base_assistant_usecase_context


def get_base_assistant(
    *,
    base_assistant_id: str,
    context: AdminBaseAssistantUsecaseContext | None = None,
) -> BaseAssistant:
    """編集対象の BaseAssistant を取得する。

    Args:
        base_assistant_id: 対象 BaseAssistant ID。

    Returns:
        未削除の BaseAssistant。

    管理画面が編集対象の存在確認込みで取得できるようにするため。
    """
    ctx = context if context is not None else admin_base_assistant_usecase_context()
    with ctx.database.connect() as conn:
        assistant = BaseAssistantRepository(conn).get(base_assistant_id)
    if assistant is None:
        raise AssistantUsecaseError("base assistant not found")
    return assistant
