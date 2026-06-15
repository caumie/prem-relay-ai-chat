"""チャット応答SSEを開く前の検証と開始保証を担当する。"""

from collections.abc import AsyncIterator

from ...infrastructure import MessageRepository
from ...models import Message, MessageStatus
from ...service.response_service import StreamEvent
from ._support import start_response
from . import ChatUsecaseContext, chat_usecase_context
from .errors import ChatUsecaseError
from .get_thread_detail import get_thread_detail


def prepare_response_stream(
    *,
    user_id: int,
    thread_id: str,
    response_id: int,
    context: ChatUsecaseContext | None = None,
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

    routeがMessageRepositoryや応答開始条件を知らずに配信応答だけを作れるようにするため。
    """
    ctx = context if context is not None else chat_usecase_context()
    detail = get_thread_detail(thread_id=thread_id, user_id=user_id, context=ctx)
    if detail is None:
        raise ChatUsecaseError("thread not found")
    with ctx.database.connect() as conn:
        try:
            response_message = MessageRepository(conn).get(response_id)
        except KeyError as exc:
            raise ChatUsecaseError("message not found") from exc
    if response_message.thread_id != thread_id:
        raise ChatUsecaseError("message not found")
    if response_message.status is MessageStatus.PROCESSING:
        start_response(
            ctx,
            user_id=user_id,
            assistant_message=response_message,
            history=detail.messages,
        )
    return response_message


async def stream_response_events(
    *,
    response_message: Message,
    context: ChatUsecaseContext | None = None,
) -> AsyncIterator[StreamEvent]:
    """準備済みassistant messageのイベント列を返す。

    Args:
        response_message: 検証と応答開始保証が済んだ assistant message。
        context: chat usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        SSEへ変換できる StreamEvent の非同期列。

    route が response service を直接参照せずに stream を返せるようにする。
    """
    ctx = context if context is not None else chat_usecase_context()
    async for event in ctx.response_service.stream_events(response_message):
        yield event
