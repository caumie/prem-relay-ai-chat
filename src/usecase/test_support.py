"""usecase テストで共有する補助オブジェクトを定義する。

このファイルは本番 usecase からは使わず、近接テスト間で共有する fake や
小さな補助だけを置く。個別の `*_test.py` 同士が import し合わないようにする。
"""

from src.models import LlmMessage, ResolvedAssistant


class FakeResponseStarter:
    """テスト用の応答開始境界を記録する。"""

    def __init__(self) -> None:
        """記録用リストを初期化する。

        Args:
            なし。

        Returns:
            None。
        """
        self.cancelled: list[int] = []

    async def cancel_response(self, message_id: int) -> bool:
        """キャンセル対象IDを記録して失敗扱いを返す。

        Args:
            message_id: キャンセル対象の assistant message ID。

        Returns:
            実行中ジョブを持たない fake として常に False。
        """
        self.cancelled.append(message_id)
        return False

    def start_response(
        self,
        *,
        message_id: int,
        messages: list[LlmMessage],
        assistant: ResolvedAssistant,
    ) -> None:
        """応答開始入力を受け取るが副作用を持たない。

        Args:
            message_id: 応答を書き込む assistant message ID。
            messages: LLM へ渡す履歴。
            assistant: 実行時設定を解決済みの assistant。

        Returns:
            None。

        UsecaseContext が要求する response service 境界だけを満たし、
        この fake 自体は応答生成を開始しない。
        """
        _ = (message_id, messages, assistant)
