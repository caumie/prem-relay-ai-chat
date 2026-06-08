"""応答開始保証ユースケースを担当する。"""

from ...models import Message
from ..context import UsecaseContext
from ._support import start_response


def ensure_response_started(
    context: UsecaseContext,
    *,
    user_id: int,
    assistant_message: Message,
    history: list[Message],
) -> None:
    """processing assistant message の応答生成が開始済みであることを保証する。"""
    start_response(
        context,
        user_id=user_id,
        assistant_message=assistant_message,
        history=history,
    )
