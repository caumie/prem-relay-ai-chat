"""admin base assistant 一覧取得ユースケースを担当する。"""

from ...infrastructure import BaseAssistantRepository
from ...models import BaseAssistant
from . import AdminBaseAssistantUsecaseContext, admin_base_assistant_usecase_context


def list_base_assistants(
    *, context: AdminBaseAssistantUsecaseContext | None = None
) -> list[BaseAssistant]:
    """管理画面で編集できる未削除 BaseAssistant 一覧を返す。

    Args:
        なし。

    Returns:
        未削除の BaseAssistant 一覧。

    admin 管理画面で base assistant 一覧を表示するため。
    """
    ctx = context if context is not None else admin_base_assistant_usecase_context()
    with ctx.database.connect() as conn:
        return BaseAssistantRepository(conn).list_active()
