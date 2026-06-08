"""admin user 一覧取得ユースケースを担当する。"""

from ...infrastructure import AuthRepository
from ...models import User
from ..context import UsecaseContext


def list_users(context: UsecaseContext) -> list[User]:
    """ユーザー一覧を返す。

    Args:
        なし。

    Returns:
        現在の有効ユーザー一覧。

    管理画面が一覧取得の詳細を知らずに済むようにするため。
    """
    with context.database.connect() as conn:
        return AuthRepository(conn).list_users()
