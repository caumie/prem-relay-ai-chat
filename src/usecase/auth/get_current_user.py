"""現在ユーザー取得ユースケースを担当する。"""

from ...models import User
from ...infrastructure import AuthRepository
from ..context import UsecaseContext


def get_current_user(context: UsecaseContext, *, user_id: int) -> User | None:
    """セッションに保存された user_id から現在ユーザーを取得する。

    Args:
        user_id: セッションから取り出したユーザーID。

    Returns:
        存在するUser、欠落または休止中ならNone。
    """
    with context.database.connect() as conn:
        user = AuthRepository(conn).get_user(user_id)
        if user is None or user.suspended_at is not None:
            return None
        return user
