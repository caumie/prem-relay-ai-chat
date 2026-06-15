"""admin user 取得ユースケースを担当する。"""

from ...infrastructure import AuthRepository
from ...models import User
from . import AdminUserUsecaseContext, admin_user_usecase_context


def get_user(
    *, user_id: int, context: AdminUserUsecaseContext | None = None
) -> User | None:
    """ユーザー ID からユーザーを返す。

    Args:
        user_id: 取得対象ユーザー ID。
        context: admin user usecase の実行依存。省略時は初期化済み runtime から取得する。

    Returns:
        見つかったユーザー。存在しなければ None。

    編集画面が repository を直接扱わずに user を取得できるようにするため。
    """
    ctx = context if context is not None else admin_user_usecase_context()
    with ctx.database.connect() as conn:
        return AuthRepository(conn).get_user(user_id)
