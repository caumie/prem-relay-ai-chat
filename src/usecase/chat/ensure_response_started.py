"""応答開始保証ユースケースを担当する。"""

from ...models import Message
from . import ChatUsecaseContext, chat_usecase_context
from ._support import start_response


def ensure_response_started(
    *,
    user_id: int,
    assistant_message: Message,
    history: list[Message],
    context: ChatUsecaseContext | None = None,
) -> None:
    """processing assistant message の応答生成が開始済みであることを保証する。"""
    ctx = context if context is not None else chat_usecase_context()
    start_response(
        ctx,
        user_id=user_id,
        assistant_message=assistant_message,
        history=history,
    )
