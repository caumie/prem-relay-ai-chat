"""チャット利用可能 assistant 一覧取得ユースケースを担当する。"""

from ...infrastructure import AssistantSelectionQuery
from ...models import AssistantOption
from . import AssistantUsecaseContext, assistant_usecase_context


def list_available_assistants(
    *, user_id: int, context: AssistantUsecaseContext | None = None
) -> list[AssistantOption]:
    """チャットで選択できる Assistant 一覧を返す。

    Args:
        user_id: 選択肢を見るユーザー ID。

    Returns:
        表示カテゴリ順に並んだ AssistantOption 一覧。
    """
    ctx = context if context is not None else assistant_usecase_context()
    with ctx.database.connect() as conn:
        return AssistantSelectionQuery(conn).list_chat_options(user_id)
