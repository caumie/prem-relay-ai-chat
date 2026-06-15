"""admin user 一覧取得ユースケースを担当する。"""

from ...infrastructure import AuthRepository
from ...models import User
from . import AdminUserUsecaseContext, admin_user_usecase_context


def list_users(context: AdminUserUsecaseContext | None = None) -> list[User]:
    """ユーザー一覧を返す。

    Args:
        context: admin user usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        現在の有効ユーザー一覧。

    管理画面が一覧取得の詳細を知らずに済むようにするため。
    """
    ctx = context if context is not None else admin_user_usecase_context()
    with ctx.database.connect() as conn:
        return AuthRepository(conn).list_users()
