"""usecase 層で共有する小さな境界 Protocol を定義する。

このファイルはHTTPやテンプレートに依存せず、複数領域から参照される
最小限の抽象だけを表す。
"""

from collections.abc import AsyncIterator
from typing import Protocol

from ..models import LlmMessage, Message, ResolvedAssistant
from ..service.response_service import StreamEvent


class ResponseStarter(Protocol):
    """assistant 応答生成の開始と中断を行う境界を表す。"""

    def start_response(
        self,
        *,
        message_id: int,
        messages: list[LlmMessage],
        assistant: ResolvedAssistant,
    ) -> None:
        """応答生成を開始する。

        Args:
            message_id: 応答を書き込むassistant message ID。
            messages: LLMへ渡す履歴。
            assistant: 実行時設定を解決済みのassistant。

        Returns:
            None。
        """
        ...

    async def cancel_response(self, message_id: int) -> bool:
        """実行中の応答生成を中断する。

        Args:
            message_id: 中断対象のassistant message ID。

        Returns:
            実行中ジョブを中断できた場合はTrue。
        """
        ...


class ResponseEventStreamer(Protocol):
    """assistant 応答生成イベントを購読する境界を表す。"""

    def stream_events(self, message: Message) -> AsyncIterator[StreamEvent]:
        """対象messageのイベント列を返す。

        Args:
            message: 購読対象のassistant message。

        Returns:
            SSEへ変換可能な StreamEvent の非同期列。
        """
        ...


class ChatResponseRuntime(ResponseStarter, ResponseEventStreamer, Protocol):
    """chat usecase が必要とする応答生成境界をまとめる。"""
