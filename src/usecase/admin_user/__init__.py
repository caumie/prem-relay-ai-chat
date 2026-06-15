"""admin user ユースケース群の公開入口と実行依存を定義する。"""

from dataclasses import dataclass

from ...infrastructure import AttachmentStorage, Database
from .. import runtime


@dataclass(frozen=True)
class AdminUserUsecaseContext:
    """admin user usecase の実行依存を表す。

    Args:
        database: ユーザー管理情報を読み書きする Database。
        password_pepper: パスワード保存に使う追加秘密値。
        attachment_storage: ユーザー削除時に添付ファイル実体を解決する保存境界。
    """

    database: Database
    password_pepper: str
    attachment_storage: AttachmentStorage


def admin_user_usecase_context() -> AdminUserUsecaseContext:
    """admin user usecase 用 context を返す。

    Returns:
        admin user usecase が使う依存だけを含む context。

    共有 runtime から管理ユーザー操作に必要な依存だけを取り出し、
    他領域の依存へ触れない形にする。
    """
    usecase_runtime = runtime.get_usecase_runtime()
    return AdminUserUsecaseContext(
        database=usecase_runtime.database,
        password_pepper=usecase_runtime.config.password_pepper,
        attachment_storage=AttachmentStorage(usecase_runtime.config.uploads_dir),
    )


from .create_user import create_user
from .delete_user import delete_user
from .get_user import get_user
from .list_users import list_users
from .suspend_user import suspend_user
from .update_user import update_user

__all__ = [
    "AdminUserUsecaseContext",
    "admin_user_usecase_context",
    "create_user",
    "delete_user",
    "get_user",
    "list_users",
    "suspend_user",
    "update_user",
]
