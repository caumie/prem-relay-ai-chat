"""ユーザー向け base assistant 選択肢一覧取得ユースケースを担当する。"""

from ...infrastructure import BaseAssistantRepository
from ...models import BaseAssistant
from . import AssistantUsecaseContext, assistant_usecase_context


def list_selectable_base_assistants(
    *, context: AssistantUsecaseContext | None = None
) -> list[BaseAssistant]:
    """ユーザーが選択できる未削除 BaseAssistant 一覧を返す。

    Args:
        なし。

    Returns:
        未削除の BaseAssistant 一覧。

    ユーザー向け assistant 作成・編集画面で選択肢を表示するため。
    """
    ctx = context if context is not None else assistant_usecase_context()
    with ctx.database.connect() as conn:
        return BaseAssistantRepository(conn).list_active()
