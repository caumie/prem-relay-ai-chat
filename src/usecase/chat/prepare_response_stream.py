"""チャット応答SSEを開く前の所有者検証を担当する。"""

from collections.abc import AsyncIterator

from ...infrastructure import MessageRepository
from ...models import Message
from ...service.response_service import StreamEvent
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
    """SSE対象messageの存在と所有threadを検証する。

    Args:
        user_id: 閲覧ユーザーID。
        thread_id: 対象Thread ID。
        response_id: assistant message ID。
        context: chat usecaseの実行依存。省略時は初期化済みruntimeから取得する。

    Returns:
        SSEで購読するMessage。

    Raises:
        ChatUsecaseError: thread/messageが存在しない、または所属が不正な場合。

    SSE GETは再接続で別workerへ届き得るため生成を開始せず、routeから
    所有者検証と購読だけを委譲する。
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
    # SSEは生成結果の観測境界であり、processingでも生成を開始しない。
    # 別workerへの再接続から同じProvider処理を重複実行させないため。
    return response_message


async def stream_response_events(
    *,
    response_message: Message,
    context: ChatUsecaseContext | None = None,
) -> AsyncIterator[StreamEvent]:
    """準備済みassistant messageのイベント列を返す。

    Args:
        response_message: 所有者検証済みのassistant message。
        context: chat usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        SSEへ変換できる StreamEvent の非同期列。

    route が response service を直接参照せずに stream を返せるようにする。
    """
    ctx = context if context is not None else chat_usecase_context()
    async for event in ctx.response_service.stream_events(response_message):
        yield event
