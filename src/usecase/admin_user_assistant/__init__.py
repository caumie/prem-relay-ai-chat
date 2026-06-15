"""admin user assistant ユースケース群の公開入口と実行依存を定義する。"""

from dataclasses import dataclass

from ...infrastructure import Database
from .. import runtime


@dataclass(frozen=True)
class AdminUserAssistantUsecaseContext:
    """admin user assistant usecase の実行依存を表す。

    Args:
        database: UserAssistant 管理情報を読み書きする Database。
    """

    database: Database


def admin_user_assistant_usecase_context() -> AdminUserAssistantUsecaseContext:
    """admin user assistant usecase 用 context を返す。

    Returns:
        admin user assistant usecase が使う依存だけを含む context。
    """
    usecase_runtime = runtime.get_usecase_runtime()
    return AdminUserAssistantUsecaseContext(
        database=usecase_runtime.database,
    )


from .create_user_assistant import create_user_assistant
from .delete_user_assistant import delete_user_assistant
from .get_manageable_user_assistant import get_manageable_user_assistant
from .list_manageable_user_assistants import list_manageable_user_assistants
from .update_user_assistant import update_user_assistant

__all__ = [
    "create_user_assistant",
    "AdminUserAssistantUsecaseContext",
    "admin_user_assistant_usecase_context",
    "delete_user_assistant",
    "get_manageable_user_assistant",
    "list_manageable_user_assistants",
    "update_user_assistant",
]
