"""admin base assistant 一覧取得ユースケースを担当する。"""

from ...infrastructure import BaseAssistantRepository
from ...models import BaseAssistant
from ..context import UsecaseContext


def list_base_assistants(context: UsecaseContext) -> list[BaseAssistant]:
    """管理画面で編集できる未削除 BaseAssistant 一覧を返す。

    Args:
        なし。

    Returns:
        未削除の BaseAssistant 一覧。

    admin 管理画面で base assistant 一覧を表示するため。
    """
    with context.database.connect() as conn:
        return BaseAssistantRepository(conn).list_active()
