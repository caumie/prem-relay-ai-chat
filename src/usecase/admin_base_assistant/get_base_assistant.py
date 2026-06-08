"""admin base assistant 取得ユースケースを担当する。"""

from ...infrastructure import BaseAssistantRepository
from ...models import BaseAssistant
from ..assistant.errors import AssistantUsecaseError
from ..context import UsecaseContext


def get_base_assistant(
    context: UsecaseContext, *, base_assistant_id: str
) -> BaseAssistant:
    """編集対象の BaseAssistant を取得する。

    Args:
        base_assistant_id: 対象 BaseAssistant ID。

    Returns:
        未削除の BaseAssistant。

    管理画面が編集対象の存在確認込みで取得できるようにするため。
    """
    with context.database.connect() as conn:
        assistant = BaseAssistantRepository(conn).get(base_assistant_id)
    if assistant is None:
        raise AssistantUsecaseError("base assistant not found")
    return assistant
