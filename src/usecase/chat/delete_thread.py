"""スレッド削除ユースケースを担当する。"""

from ...infrastructure import ThreadRepository
from . import ChatUsecaseContext, chat_usecase_context
from .errors import ChatUsecaseError


def delete_thread(
    *, thread_id: str, user_id: int, context: ChatUsecaseContext | None = None
) -> bool:
    """指定ユーザーが所有するスレッドを論理削除する。"""
    ctx = context if context is not None else chat_usecase_context()
    with ctx.database.connect() as conn:
        deleted = ThreadRepository(conn).logical_delete(
            thread_id=thread_id,
            user_id=user_id,
        )
        if not deleted:
            raise ChatUsecaseError("thread not found")
        conn.commit()
    return True
