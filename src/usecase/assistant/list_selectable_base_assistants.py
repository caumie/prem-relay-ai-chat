"""ユーザー向け base assistant 選択肢一覧取得ユースケースを担当する。"""

from ...infrastructure import BaseAssistantRepository
from ...models import BaseAssistant
from ..context import UsecaseContext


def list_selectable_base_assistants(context: UsecaseContext) -> list[BaseAssistant]:
    """ユーザーが選択できる未削除 BaseAssistant 一覧を返す。

    Args:
        なし。

    Returns:
        未削除の BaseAssistant 一覧。

    ユーザー向け assistant 作成・編集画面で選択肢を表示するため。
    """
    with context.database.connect() as conn:
        return BaseAssistantRepository(conn).list_active()
