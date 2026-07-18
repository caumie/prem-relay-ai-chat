"""チャット応答生成のキャンセルユースケースを担当する。"""

from dataclasses import replace

from ...infrastructure import MessageRepository, utcnow
from ...models import MessageStatus
from . import ChatUsecaseContext, chat_usecase_context
from .errors import ChatUsecaseError
from .get_thread_detail import get_thread_detail


async def cancel_response(
    *,
    user_id: int,
    thread_id: str,
    message_id: int,
    context: ChatUsecaseContext | None = None,
) -> None:
    """生成中assistant messageの応答生成を中断する。

    Args:
        user_id: 操作ユーザーID。
        thread_id: 対象Thread ID。
        message_id: 対象assistant message ID。
        context: chat usecaseの実行依存。省略時は初期化済みruntimeから取得する。

    Returns:
        None。

    Raises:
        ChatUsecaseError: thread/messageが存在しない、または生成中でない場合。

    response serviceがジョブを持たない場合のfailed収束も含め、
    routeへMessageRepository更新を漏らさないため。
    """
    ctx = context if context is not None else chat_usecase_context()
    detail = get_thread_detail(thread_id=thread_id, user_id=user_id, context=ctx)
    if detail is None:
        raise ChatUsecaseError("thread not found")
    with ctx.database.connect() as conn:
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
    # process-local Jobのcancelはawaitを伴う。待機中に別処理がterminalへ
    # 確定できるよう、DB connectionと古いtransactionを保持しない。
    cancelled = await ctx.response_service.cancel_response(message_id)
    if not cancelled:
        # 非owner workerではProvider Task自体は止められない。新しいconnectionから
        # processingだけをfailedへ更新し、ownerの後着完了による上書きと、
        # await中に確定したterminalへの上書きを防ぐ。
        with ctx.database.connect() as conn:
            MessageRepository(conn).update_processing_to_terminal(
                replace(
                    message,
                    status=MessageStatus.FAILED,
                    updated_at=utcnow(),
                )
            )
            conn.commit()
