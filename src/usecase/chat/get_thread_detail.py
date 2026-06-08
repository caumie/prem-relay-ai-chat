"""スレッド詳細取得ユースケースを担当する。"""

from ...infrastructure import ChatThreadQuery
from ...models import ThreadDetail
from ..context import UsecaseContext


def get_thread_detail(
    context: UsecaseContext, *, thread_id: str, user_id: int
) -> ThreadDetail | None:
    """指定ユーザーが所有するスレッド詳細を取得する。"""
    with context.database.connect() as conn:
        return ChatThreadQuery(conn).get_detail_for_user(
            thread_id=thread_id,
            user_id=user_id,
        )
