"""チャット応答SSEを開く前の検証と開始保証を担当する。"""

from ...infrastructure import MessageRepository
from ...models import Message, MessageStatus
from ._support import start_response
from ..context import UsecaseContext
from .errors import ChatUsecaseError
from .get_thread_detail import get_thread_detail


def prepare_response_stream(
    context: UsecaseContext,
    *,
    user_id: int,
    thread_id: str,
    response_id: int,
) -> Message:
    """SSE対象messageを検証し、必要なら応答生成を開始する。

    Args:
        user_id: 閲覧ユーザーID。
        thread_id: 対象Thread ID。
        response_id: assistant message ID。

    Returns:
        SSEで購読するMessage。

    Raises:
        ChatUsecaseError: thread/messageが存在しない、または所属が不正な場合。

    routeがMessageRepositoryや応答開始条件を知らずにStreamingResponseだけを
    作れるようにするため。
    """
    detail = get_thread_detail(context, thread_id=thread_id, user_id=user_id)
    if detail is None:
        raise ChatUsecaseError("thread not found")
    with context.database.connect() as conn:
        try:
            response_message = MessageRepository(conn).get(response_id)
        except KeyError as exc:
            raise ChatUsecaseError("message not found") from exc
    if response_message.thread_id != thread_id:
        raise ChatUsecaseError("message not found")
    if response_message.status is MessageStatus.PROCESSING:
        start_response(
            context,
            user_id=user_id,
            assistant_message=response_message,
            history=detail.messages,
        )
    return response_message
