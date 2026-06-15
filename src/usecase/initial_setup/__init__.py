"""初回セットアップユースケース群の公開入口と実行依存を定義する。"""

from dataclasses import dataclass

from ...infrastructure import Database
from .. import runtime


@dataclass(frozen=True)
class InitialSetupUsecaseContext:
    """初回セットアップ usecase の実行依存を表す。

    Args:
        database: ユーザー管理情報を読み書きする Database。
        password_pepper: パスワード保存に使う追加秘密値。
    """

    database: Database
    password_pepper: str


def initial_setup_usecase_context() -> InitialSetupUsecaseContext:
    """初回セットアップ usecase 用 context を返す。

    Returns:
        初回セットアップ usecase が使う依存だけを含む context。

    共有 runtime から初回管理者作成に必要な依存だけを取り出し、
    presentation がDBや設定を直接参照しない形にする。
    """
    usecase_runtime = runtime.get_usecase_runtime()
    return InitialSetupUsecaseContext(
        database=usecase_runtime.database,
        password_pepper=usecase_runtime.config.password_pepper,
    )


from .create_initial_admin import (
    InitialAdminAlreadyExistsError,
    create_initial_admin,
)
from .get_initial_setup_status import (
    InitialSetupStatus,
    get_initial_setup_status,
)
from .startup_database import (
    fail_processing_assistant_messages,
    initialize_database_schema,
)

__all__ = [
    "InitialAdminAlreadyExistsError",
    "InitialSetupStatus",
    "InitialSetupUsecaseContext",
    "create_initial_admin",
    "fail_processing_assistant_messages",
    "get_initial_setup_status",
    "initial_setup_usecase_context",
    "initialize_database_schema",
]
