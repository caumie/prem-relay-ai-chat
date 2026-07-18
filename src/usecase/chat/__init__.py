"""chat ユースケース群の公開入口と実行依存を定義する。"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ...infrastructure import AttachmentStorage, Database
from ...models import ConnectionProvider
from .. import runtime
from ..type import ChatResponseRuntime


@dataclass(frozen=True)
class ChatUsecaseContext:
    """chat usecase の実行依存を表す。

    Args:
        database: thread/message/attachment を読み書きする Database。
        response_service: assistant 応答生成の開始・中断・購読境界。
        uploads_dir: LLM入力へ添付を渡す際の保存ルート。
        attachment_storage: 添付ファイル実体の保存・解決境界。
        load_connection_providers: 接続先定義を読み込む関数。
    """

    database: Database
    response_service: ChatResponseRuntime
    uploads_dir: Path
    attachment_storage: AttachmentStorage
    load_connection_providers: Callable[[], list[ConnectionProvider]]


def chat_usecase_context() -> ChatUsecaseContext:
    """chat usecase 用 context を返す。

    Returns:
        chat usecase が使う依存だけを含む context。
    """
    usecase_runtime = runtime.get_usecase_runtime()
    return ChatUsecaseContext(
        database=usecase_runtime.database,
        response_service=usecase_runtime.response_service,
        uploads_dir=usecase_runtime.config.uploads_dir,
        attachment_storage=usecase_runtime.attachment_storage,
        load_connection_providers=usecase_runtime.load_connection_providers,
    )


from .add_message import add_message
from .build_chat_page import ChatPage, build_chat_page
from .cancel_response import cancel_response
from .create_chat import create_chat
from .delete_thread import delete_thread
from .errors import ChatUsecaseError
from .get_attachment import AttachmentDownload, get_attachment, get_attachment_download
from .get_thread_detail import get_thread_detail
from .prepare_response_stream import prepare_response_stream, stream_response_events
from .rename_thread import rename_thread
from .save_message_attachments import save_message_attachments

__all__ = [
    "ChatUsecaseError",
    "ChatPage",
    "ChatUsecaseContext",
    "add_message",
    "build_chat_page",
    "cancel_response",
    "chat_usecase_context",
    "create_chat",
    "delete_thread",
    "get_attachment_download",
    "get_attachment",
    "get_thread_detail",
    "prepare_response_stream",
    "rename_thread",
    "save_message_attachments",
    "stream_response_events",
    "AttachmentDownload",
]
