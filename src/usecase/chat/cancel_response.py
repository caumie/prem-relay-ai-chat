"""チャット応答生成のキャンセルユースケースを担当する。"""

from dataclasses import replace

from ...infrastructure import MessageRepository, utcnow
from ...models import MessageStatus
from ..context import UsecaseContext
from .errors import ChatUsecaseError
from .get_thread_detail import get_thread_detail


async def cancel_response(
    context: UsecaseContext,
    *,
    user_id: int,
    thread_id: str,
    message_id: int,
) -> None:
    """生成中assistant messageの応答生成を中断する。

    Args:
        user_id: 操作ユーザーID。
        thread_id: 対象Thread ID。
        message_id: 対象assistant message ID。

    Returns:
        None。

    Raises:
        ChatUsecaseError: thread/messageが存在しない、または生成中でない場合。

    response serviceがジョブを持たない場合のfailed収束も含め、
    routeへMessageRepository更新を漏らさないため。
    """
    detail = get_thread_detail(context, thread_id=thread_id, user_id=user_id)
    if detail is None:
        raise ChatUsecaseError("thread not found")
    with context.database.connect() as conn:
        repo = MessageRepository(conn)
        try:
            message = repo.get(message_id)
        except KeyError as exc:
            raise ChatUsecaseError("message not found") from exc
        if (
            message.thread_id != thread_id
            or message.status is not MessageStatus.PROCESSING
        ):
            raise ChatUsecaseError("message not processing")
        cancelled = await context.response_service.cancel_response(message_id)
        if not cancelled:
            repo.update(
                replace(
                    message,
                    status=MessageStatus.FAILED,
                    updated_at=utcnow(),
                )
            )
            conn.commit()
