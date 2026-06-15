"""スレッド名変更ユースケースを担当する。"""

from dataclasses import replace

from ...infrastructure import ThreadRepository, utcnow
from ...models import Thread
from ._support import normalize_thread_title
from . import ChatUsecaseContext, chat_usecase_context
from .errors import ChatUsecaseError


def rename_thread(
    *,
    thread_id: str,
    user_id: int,
    title: str,
    context: ChatUsecaseContext | None = None,
) -> Thread:
    """指定ユーザーが所有するスレッドのタイトルを更新する。"""
    ctx = context if context is not None else chat_usecase_context()
    with ctx.database.connect() as conn:
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
