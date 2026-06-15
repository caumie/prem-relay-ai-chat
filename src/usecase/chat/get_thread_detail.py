"""スレッド詳細取得ユースケースを担当する。"""

from ...infrastructure import ChatThreadQuery
from ...models import ThreadDetail
from . import ChatUsecaseContext, chat_usecase_context


def get_thread_detail(
    *, thread_id: str, user_id: int, context: ChatUsecaseContext | None = None
) -> ThreadDetail | None:
    """指定ユーザーが所有するスレッド詳細を取得する。"""
    ctx = context if context is not None else chat_usecase_context()
    with ctx.database.connect() as conn:
        return ChatThreadQuery(conn).get_detail_for_user(
            thread_id=thread_id,
            user_id=user_id,
        )
