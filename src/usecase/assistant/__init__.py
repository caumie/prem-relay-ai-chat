"""assistant ユースケース群の公開入口と実行依存を定義する。"""

from collections.abc import Callable
from dataclasses import dataclass

from ...infrastructure import Database
from ...models import ConnectionProvider
from .. import runtime


@dataclass(frozen=True)
class AssistantUsecaseContext:
    """assistant usecase の実行依存を表す。

    Args:
        database: assistant 情報を読み書きする Database。
        load_connection_providers: 接続先定義を読み込む関数。
    """

    database: Database
    load_connection_providers: Callable[[], list[ConnectionProvider]]


def assistant_usecase_context() -> AssistantUsecaseContext:
    """assistant usecase 用 context を返す。

    Returns:
        assistant usecase が使う依存だけを含む context。
    """
    usecase_runtime = runtime.get_usecase_runtime()
    return AssistantUsecaseContext(
        database=usecase_runtime.database,
        load_connection_providers=usecase_runtime.load_connection_providers,
    )


from .create_user_assistant import create_user_assistant
from .delete_user_assistant import delete_user_assistant
from .errors import AssistantUsecaseError
from .get_manageable_user_assistant import get_manageable_user_assistant
from .list_available_assistants import list_available_assistants
from .list_manageable_user_assistants import list_manageable_user_assistants
from .list_selectable_base_assistants import list_selectable_base_assistants
from .resolve_runtime_assistant import resolve_runtime_assistant
from .update_user_assistant import update_user_assistant

__all__ = [
    "AssistantUsecaseError",
    "AssistantUsecaseContext",
    "assistant_usecase_context",
    "create_user_assistant",
    "delete_user_assistant",
    "get_manageable_user_assistant",
    "list_available_assistants",
    "list_manageable_user_assistants",
    "list_selectable_base_assistants",
    "resolve_runtime_assistant",
    "update_user_assistant",
]
