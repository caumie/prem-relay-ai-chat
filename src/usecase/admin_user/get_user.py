"""admin user 取得ユースケースを担当する。"""

from ...infrastructure import AuthRepository
from ...models import User
from ..context import UsecaseContext


def get_user(context: UsecaseContext, user_id: int) -> User | None:
    """ユーザー ID からユーザーを返す。

    Args:
        user_id: 取得対象ユーザー ID。

    Returns:
        見つかったユーザー。存在しなければ None。

    編集画面が repository を直接扱わずに user を取得できるようにするため。
    """
    with context.database.connect() as conn:
        return AuthRepository(conn).get_user(user_id)
