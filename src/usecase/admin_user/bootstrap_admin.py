"""初期管理者作成ユースケースを担当する。"""

from ...auth_password import hash_password
from ...infrastructure import AuthRepository
from ...models import User
from ..context import UsecaseContext


def bootstrap_admin(context: UsecaseContext, *, login_name: str, password: str) -> User:
    """初期管理者ユーザーを冪等に作成して返す。

    Args:
        login_name: 保証したい管理者ログイン名。
        password: 管理者へ設定する平文パスワード。

    Returns:
        既存または新規作成された管理者ユーザー。

    アプリ起動処理が認証テーブルの詳細を持たずに admin 存在保証だけを扱えるようにするため。
    """
    with context.database.connect() as conn:
        repo = AuthRepository(conn)
        existing = repo.get_by_login_name(login_name)
        if existing is not None:
            return existing
        user = repo.save(
            User(id=0, login_name=login_name, is_admin=True),
            password_hash=hash_password(password, context.password_pepper),
        )
        conn.commit()
        return user
