"""usecase 層の実行依存を束ねる共有 context を定義する。

このファイルはHTTPやテンプレートに依存せず、usecaseがDB、外部設定、
ファイル保存、応答生成境界へアクセスするための依存だけを表す。
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..infrastructure import AttachmentStorage, Database
from ..models import ConnectionProvider, LlmMessage, ResolvedAssistant


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


@dataclass(frozen=True)
class UsecaseContext:
    """usecaseを実行するためのアプリ境界依存を保持する。

    Attributes:
        database: 永続化境界。
        password_pepper: パスワードhash/verify用の追加秘密値。
        response_service: assistant応答生成の開始・中断境界。
        uploads_dir: 保存済み添付をLLM入力へ変換する際の保存ルート。
        attachment_storage: 添付ファイル実体の保存・解決境界。
        load_connection_providers: 固定接続先定義を読み込む関数。
    """

    database: Database
    password_pepper: str
    response_service: ResponseStarter
    uploads_dir: Path
    attachment_storage: AttachmentStorage
    load_connection_providers: Callable[[], list[ConnectionProvider]]
