"""admin base assistant ユースケース群の公開入口と実行依存を定義する。"""

from collections.abc import Callable
from dataclasses import dataclass

from ...infrastructure import Database
from ...models import ConnectionProvider
from .. import runtime


@dataclass(frozen=True)
class AdminBaseAssistantUsecaseContext:
    """admin base assistant usecase の実行依存を表す。

    Args:
        database: BaseAssistant 管理情報を読み書きする Database。
        load_connection_providers: 接続先定義を読み込む関数。
    """

    database: Database
    load_connection_providers: Callable[[], list[ConnectionProvider]]


def admin_base_assistant_usecase_context() -> AdminBaseAssistantUsecaseContext:
    """admin base assistant usecase 用 context を返す。

    Returns:
        admin base assistant usecase が使う依存だけを含む context。

    共有 runtime から BaseAssistant 管理に必要な依存だけを取り出す。
    """
    usecase_runtime = runtime.get_usecase_runtime()
    return AdminBaseAssistantUsecaseContext(
        database=usecase_runtime.database,
        load_connection_providers=usecase_runtime.load_connection_providers,
    )


from .create_base_assistant import create_base_assistant
from .delete_base_assistant import delete_base_assistant
from .get_base_assistant import get_base_assistant
from .list_base_assistants import list_base_assistants
from .list_connection_providers import list_connection_providers
from .update_base_assistant import update_base_assistant

__all__ = [
    "create_base_assistant",
    "AdminBaseAssistantUsecaseContext",
    "admin_base_assistant_usecase_context",
    "delete_base_assistant",
    "get_base_assistant",
    "list_base_assistants",
    "list_connection_providers",
    "update_base_assistant",
]
