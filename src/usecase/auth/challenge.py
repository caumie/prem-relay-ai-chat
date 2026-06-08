"""認証チャレンジユースケースを担当する。"""

from ...auth_password import verify_password
from ...models import User
from ...infrastructure import AuthRepository
from ..context import UsecaseContext


def challenge(context: UsecaseContext, *, login_name: str, password: str) -> User | None:
    """ログイン名とパスワードでユーザーを認証する。

    Args:
        login_name: フォームから受け取ったログイン名。
        password: フォームから受け取った平文パスワード。

    Returns:
        認証できたUser、失敗時はNone。
    """
    with context.database.connect() as conn:
        repo = AuthRepository(conn)
        user = repo.get_by_login_name(login_name)
        if user is None or user.suspended_at is not None:
            return None
        password_hash = repo.get_password_hash_by_login_name(login_name)
        if password_hash is None:
            return None
        if not verify_password(password, password_hash, context.password_pepper):
            return None
        return user
