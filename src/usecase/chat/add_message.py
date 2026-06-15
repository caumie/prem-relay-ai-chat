"""既存スレッドへの投稿ユースケースを担当する。"""

from ...models import Attachment, PendingUpload
from . import ChatUsecaseContext, chat_usecase_context
from ._support import ChatMutationResult, append_thread_mutation
from .errors import ChatUsecaseError


async def add_message(
    *,
    user_id: int,
    thread_id: str,
    content: str,
    assistant_id: str | None,
    attachments: list[Attachment] | None = None,
    uploads: list[PendingUpload] | None = None,
    context: ChatUsecaseContext | None = None,
) -> ChatMutationResult:
    """既存スレッドへ添付、ユーザー発言、assistant placeholderを追加する。

    Args:
        user_id: 投稿者のユーザーID。
        thread_id: 投稿先Thread ID。
        content: フォームから受け取った本文。
        assistant_id: 投稿先assistant ID。
        attachments: すでに保存済みの添付metadata。
        uploads: presentation層で変換した未保存アップロード一覧。

    Returns:
        更新対象Threadと追加Messageの組。

    投稿時の添付保存をusecase内へ置き、HTTP層がDB保存順序を持たないようにする。
    """
    ctx = context if context is not None else chat_usecase_context()
    result = await append_thread_mutation(
        ctx,
        user_id=user_id,
        thread_id=thread_id,
        content=content,
        assistant_id=assistant_id,
        attachments=attachments or [],
        uploads=uploads or [],
    )
    if result is None:
        raise ChatUsecaseError("thread not found")
    return result
