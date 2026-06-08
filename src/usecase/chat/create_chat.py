"""チャット作成ユースケースを担当する。"""

from ...models import Attachment, PendingUpload
from ..context import UsecaseContext
from ._support import ChatMutationResult, create_thread_mutation


async def create_chat(
    context: UsecaseContext,
    *,
    user_id: int,
    content: str,
    assistant_id: str | None,
    attachments: list[Attachment] | None = None,
    uploads: list[PendingUpload] | None = None,
) -> ChatMutationResult:
    """新しいスレッド、初回発言、添付、assistant placeholderを保存する。

    Args:
        user_id: 投稿者のユーザーID。
        content: フォームから受け取った本文。
        assistant_id: 投稿先assistant ID。
        attachments: すでに保存済みの添付metadata。
        uploads: presentation層でFastAPI型から変換した未保存アップロード一覧。

    Returns:
        作成されたThreadとMessageの組。

    添付保存を投稿ユースケース内で行い、presentationが保存順序やcommitを
    知らなくてよい境界にする。
    """
    return await create_thread_mutation(
        context,
        user_id=user_id,
        content=content,
        assistant_id=assistant_id,
        attachments=attachments or [],
        uploads=uploads or [],
    )
