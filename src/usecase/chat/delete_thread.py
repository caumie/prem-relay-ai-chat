"""スレッド削除ユースケースを担当する。"""

from ...infrastructure import ThreadRepository
from ..context import UsecaseContext
from .errors import ChatUsecaseError


def delete_thread(context: UsecaseContext, *, thread_id: str, user_id: int) -> bool:
    """指定ユーザーが所有するスレッドを論理削除する。"""
    with context.database.connect() as conn:
        deleted = ThreadRepository(conn).logical_delete(
            thread_id=thread_id,
            user_id=user_id,
        )
        if not deleted:
            raise ChatUsecaseError("thread not found")
        conn.commit()
    return True
