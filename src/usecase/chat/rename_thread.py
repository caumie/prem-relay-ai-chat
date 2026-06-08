"""スレッド名変更ユースケースを担当する。"""

from dataclasses import replace

from ...infrastructure import ThreadRepository, utcnow
from ...models import Thread
from ._support import normalize_thread_title
from ..context import UsecaseContext
from .errors import ChatUsecaseError


def rename_thread(
    context: UsecaseContext, *, thread_id: str, user_id: int, title: str
) -> Thread:
    """指定ユーザーが所有するスレッドのタイトルを更新する。"""
    with context.database.connect() as conn:
        repo = ThreadRepository(conn)
        thread = repo.get(thread_id, user_id)
        if thread is None:
            raise ChatUsecaseError("thread not found")
        renamed = repo.update(
            replace(
                thread,
                title=normalize_thread_title(title),
                updated_at=utcnow(),
            )
        )
        if renamed is None:
            raise ChatUsecaseError("thread not found")
        conn.commit()
    return renamed
